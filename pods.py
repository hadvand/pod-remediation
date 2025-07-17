import os
import time
import subprocess
import requests
import re
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

LLM_API_URL = "<endpoint>"
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": "Bearer <jwt>"
}
SCENARIO_FILES_DIR = "scenarios"

console = Console()

def run_command(command, check=True):
    """Executes a shell command and returns its output."""
    try:
        result = subprocess.run(
            command, shell=True, check=check, capture_output=True, text=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        console.print(f"[bold red]Error executing command: {command}[/bold red]")
        console.print(f"[red]Stderr: {e.stderr.strip()}[/red]")
        if check:
            raise
        return e.stderr.strip()

def call_llm(prompt, max_tokens=4096):
    """Sends a prompt to the LLM API and returns the response."""
    payload = {
        "model": "tesla/llmgateway/bedrock-claude-3-haiku",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "max_tokens": max_tokens,
        "temperature": 0.01,
        "top_p": 1,
        "top_k": 50,
    }
    try:
        response = requests.post(LLM_API_URL, json=payload, headers=HEADERS, timeout=120)
        response.raise_for_status()
        response_data = response.json()
        message = response_data["choices"][0].get("message", {})
        return message.get("content", "Error: 'content' key not found in message.")
    except requests.exceptions.RequestException as e:
        return f"API Request Error: {e}"

def display_panel(content, title, style="cyan", is_syntax=False, lexer=None):
    """Displays content in a styled panel."""
    if is_syntax:
        display_content = Syntax(content, lexer, theme="monokai", line_numbers=True)
    else:
        display_content = Text(content, overflow="fold")
    console.print(Panel(display_content, title=title, border_style=style, expand=False))


def perceive_context(pod_name, classification):
    """Collects the diagnostic context based on the failure classification."""
    context = {}
    
    desc_cmd = f"kubectl describe pod {pod_name}"
    context["pod_description"] = run_command(desc_cmd, check=False)

    if classification == "SchedulingFailure":
        context["node_descriptions"] = run_command("kubectl describe nodes", check=False)
    elif classification == "ImagePullFailure":
        pass
    elif classification == "ConfigurationFailure":
        context["configmaps_in_namespace"] = run_command("kubectl get configmaps", check=False)
    elif classification == "InitializationFailure":
        init_container_name = ""
        pod_desc_lines = context.get("pod_description", "").split('\n')
        try:
            init_section_index = pod_desc_lines.index('Init Containers:')
            for line in pod_desc_lines[init_section_index + 1:]:
                if line.strip().endswith(':'):
                    init_container_name = line.strip().replace(':', '')
                    break
        except ValueError:
            init_container_name = ""

        if init_container_name:
            context["init_container_logs"] = run_command(f"kubectl logs {pod_name} -c {init_container_name} --previous", check=False)
    elif classification == "RuntimeCrash":
        context["container_logs"] = run_command(f"kubectl logs {pod_name} --previous", check=False)
    elif classification == "HealthCheckFailure":
        app_label = pod_name.replace('-pod', '').replace('bad-readiness-', 'bad-readiness')
        context["service_endpoints"] = run_command(f"kubectl get endpoints -l app={app_label}", check=False)
        
    return context

def reason_llm(context_package, prompt_template):
    """Formats the context into a prompt and calls the LLM."""
    prompt = prompt_template
    
    if "kubectl_get_pod_output" in context_package:
        prompt = prompt.replace("{kubectl_get_pod_output}", context_package["kubectl_get_pod_output"])
        return call_llm(prompt)

    for key, value in context_package.items():
        placeholder = "{" + key + "}"
        prompt = prompt.replace(placeholder, str(value))

    prompt = re.sub(r'--- [A-Z_]+ ---\n\{[a-z_]+\}\n--- END [A-Z_]+ ---', '', prompt)
    
    return call_llm(prompt)

def act_display_results(scenario, context, llm_response):
    """Displays the collected context and LLM analysis."""
    display_panel(scenario['description'], "Scenario Description", "bold magenta")
    
    context_str = ""
    for key, value in context.items():
        context_str += f"--- {key.upper()} ---\n{value}\n\n"
    display_panel(context_str.strip(), "Diagnostic Context Package Sent to LLM", "yellow", is_syntax=True, lexer="yaml")
    
    display_panel(llm_response, "LLM Analysis & Remediation Plan", "bold green")

def get_worker_node():
    """Gets the name of the first available worker node."""
    nodes_output = run_command("kubectl get nodes --no-headers -o custom-columns=NAME:.metadata.name,ROLE:.metadata.labels.node-role\\.kubernetes\\.io/master")
    for line in nodes_output.strip().split('\n'):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) == 1 or (len(parts) > 1 and parts[1] == "<none>"):
            return parts[0]
    return None

node_name = get_worker_node()

SCENARIOS = {
    "1_insufficient_cpu": {
        "description": "A pod requests more CPU than any node can provide, causing a 'Pending' state.",
        "manifest_filename": "1_insufficient_cpu.yaml",
        "pod_name_pattern": "high-cpu-app-",
        "cleanup_kind": "deployment",
        "cleanup_name": "high-cpu-app",
    },
    "2_taint_toleration": {
        "description": "A pod cannot be scheduled because it lacks a toleration for a taint applied to all available nodes.",
        "manifest_filename": "2_taint_toleration.yaml",
        "pre_run_command": "kubectl taint nodes {node_name} special-workload=true:NoSchedule",
        "post_run_command": "kubectl taint nodes {node_name} special-workload=true:NoSchedule-",
        "pod_name_pattern": "app-needs-toleration",
        "cleanup_kind": "pod",
        "cleanup_name": "app-needs-toleration",
    },
    "3_node_selector": {
        "description": "A pod cannot be scheduled because its nodeSelector specifies a label that does not exist on any node.",
        "manifest_filename": "3_node_selector.yaml",
        "pod_name_pattern": "app-needs-label",
        "cleanup_kind": "pod",
        "cleanup_name": "app-needs-label",
    },
    "4_invalid_image_name": {
        "description": "A pod enters ImagePullBackOff due to a typo in the container image name.",
        "manifest_filename": "4_invalid_image_name.yaml",
        "pod_name_pattern": "bad-image-pod",
        "cleanup_kind": "pod",
        "cleanup_name": "bad-image-pod",
    },
    "6_missing_configmap": {
        "description": "A pod fails with CreateContainerConfigError because it references a ConfigMap that does not exist.",
        "manifest_filename": "6_missing_configmap.yaml",
        "pod_name_pattern": "app-needs-config",
        "cleanup_kind": "pod",
        "cleanup_name": "app-needs-config",
    },
    "7_failing_init_container": {
        "description": "A pod is stuck in Init:CrashLoopBackOff because its initContainer fails repeatedly.",
        "manifest_filename": "7_failing_init_container.yaml",
        "pod_name_pattern": "app-with-failing-init",
        "cleanup_kind": "pod",
        "cleanup_name": "app-with-failing-init",
    },
    "8_app_logic_error": {
        "description": "A pod enters CrashLoopBackOff because the application code exits with an error.",
        "manifest_filename": "8_app_logic_error.yaml",
        "pod_name_pattern": "buggy-app-pod",
        "cleanup_kind": "pod",
        "cleanup_name": "buggy-app-pod",
    },
    "9_oomkilled": {
        "description": "A pod is terminated with OOMKilled because it consumes more memory than its limit.",
        "manifest_filename": "9_oomkilled.yaml",
        "pod_name_pattern": "oom-pod",
        "cleanup_kind": "pod",
        "cleanup_name": "oom-pod",
    },
    "10_bad_liveness_probe": {
        "description": "A healthy pod enters CrashLoopBackOff because it is repeatedly killed by a misconfigured liveness probe.",
        "manifest_filename": "10_bad_liveness_probe.yaml",
        "pod_name_pattern": "bad-liveness-pod",
        "cleanup_kind": "pod",
        "cleanup_name": "bad-liveness-pod",
    },
    "11_bad_readiness_probe": {
        "description": "A running pod does not receive traffic because its readiness probe is failing.",
        "manifest_filename": "11_bad_readiness_probe.yaml",
        "pod_name_pattern": "bad-readiness-pod",
        "cleanup_kind": "pod",
        "cleanup_name": "bad-readiness-pod",
    },
}


def get_pod_name(pattern):
    """Finds a pod name that matches a given pattern."""
    time.sleep(5)
    for _ in range(5):
        pods_output = run_command("kubectl get pods -o name", check=False)
        for pod_line in pods_output.split('\n'):
            pod_name = pod_line.replace("pod/", "")
            if pod_name.startswith(pattern):
                return pod_name
        time.sleep(2)
    return None

def main():
    console.rule("[bold blue]Kubernetes LLM Diagnostics Test Harness[/bold blue]")
    
    node_for_taint = get_worker_node()
    if not node_for_taint:
        console.print("[bold red]Could not find a worker node for taint tests. Scenario 2 will be skipped.[/bold red]")

    for scenario_id, scenario_info in SCENARIOS.items():
        console.rule(f"[bold]Running Scenario: {scenario_id}[/bold]")
        
        if "taint" in scenario_id and not node_for_taint:
            console.print("[yellow]Skipping taint scenario as no suitable worker node was found.[/yellow]")
            continue

        if "pre_run_command" in scenario_info:
            command = scenario_info["pre_run_command"].format(node_name=node_for_taint)
            display_panel(command, "Pre-run Command", "blue", is_syntax=True, lexer="bash")
            run_command(command)

        manifest_path = os.path.join(SCENARIO_FILES_DIR, scenario_info["manifest_filename"])
        
        # Read the manifest content from the YAML file
        with open(manifest_path, "r") as f:
            manifest_content = f.read()
        
        display_panel(manifest_content, f"Applying Manifest: {manifest_path}", "red", is_syntax=True, lexer="yaml")
        run_command(f"kubectl apply -f {manifest_path}")
        console.print("[italic]Waiting for 15 seconds for pod to enter error state...[/italic]")
        time.sleep(15)

        pod_name = get_pod_name(scenario_info["pod_name_pattern"])
        if not pod_name:
            console.print("[bold red]Could not find the pod for this scenario. Skipping.[/bold red]")
        else:
            display_panel(f"Identified failing pod: {pod_name}", "Pod Identification", "cyan")

            console.print("\n[bold yellow]>> Step 1: Classifying failure type...[/bold yellow]")
            get_pod_output = run_command(f"kubectl get pod {pod_name}")
            classification_prompt = """
You are an expert Kubernetes SRE. Classify the failure of the pod below into ONE of these categories:
SchedulingFailure, ImagePullFailure, ConfigurationFailure, InitializationFailure, RuntimeCrash, HealthCheckFailure
--- POD DATA ---
{kubectl_get_pod_output}
--- END POD DATA ---
Respond with ONLY the category name.
"""
            classification = reason_llm({"kubectl_get_pod_output": get_pod_output}, classification_prompt).strip()
            display_panel(classification, "LLM Classification Result", "green")

            console.print("\n[bold yellow]>> Step 2: Collecting detailed context based on classification...[/bold yellow]")
            full_context = perceive_context(pod_name, classification)

            console.print("\n[bold yellow]>> Step 3: Requesting deep diagnosis and remediation from LLM...[/bold yellow]")
            diagnosis_prompt_template = """
You are an expert Kubernetes SRE providing a detailed root cause analysis and remediation plan.
Analyze the following diagnostic data to determine the precise root cause of the failure.

### DIAGNOSTIC CONTEXT PACKAGE START ###
--- POD_DESCRIPTION ---
{pod_description}
--- END POD_DESCRIPTION ---

--- NODE_DESCRIPTIONS ---
{node_descriptions}
--- END NODE_DESCRIPTIONS ---

--- CONFIGMAPS_IN_NAMESPACE ---
{configmaps_in_namespace}
--- END CONFIGMAPS_IN_NAMESPACE ---

--- INIT_CONTAINER_LOGS ---
{init_container_logs}
--- END INIT_CONTAINER_LOGS ---

--- CONTAINER_LOGS ---
{container_logs}
--- END CONTAINER_LOGS ---

--- SERVICE_ENDPOINTS ---
{service_endpoints}
--- END SERVICE_ENDPOINTS ---
### DIAGNOSTIC CONTEXT PACKAGE END ###

Provide:
1.  **Root Cause:** A concise explanation of the failure.
2.  **Detailed Analysis:** An in-depth explanation of the evidence.
3.  **Remediation Plan:** Step-by-step instructions with corrected YAML or commands.
"""
            diagnosis_result = reason_llm(full_context, diagnosis_prompt_template)
            
            act_display_results(scenario_info, full_context, diagnosis_result)
        
        display_panel(f"Cleaning up resources for scenario {scenario_id}", "Cleanup", "red")
        run_command(f"kubectl delete {scenario_info['cleanup_kind']} {scenario_info['cleanup_name']} --grace-period=0 --force", check=False)
        if "post_run_command" in scenario_info:
            command = scenario_info["post_run_command"].format(node_name=node_for_taint)
            display_panel(command, "Post-run Cleanup Command", "blue", is_syntax=True, lexer="bash")
            run_command(command, check=False)
        
        time.sleep(5)
        
        input("Press Enter to continue to the next scenario...")
        os.system('clear')

    console.rule("[bold blue]Demonstration Complete[/bold blue]")

if __name__ == "__main__":
    main()
