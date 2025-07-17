# Kubernetes LLM Diagnostics Test Harness

A tool for testing and demonstrating AI-powered Kubernetes pod failure diagnosis and remediation using SWO LLM Gateway.

## Overview

This script creates various Kubernetes pod failure scenarios and uses an LLM to automatically diagnose and provide remediation plans. It demonstrates how AI can assist in troubleshooting common Kubernetes issues by analyzing pod states, logs, and cluster configuration.
<img width="1402" height="1293" alt="image" src="https://github.com/user-attachments/assets/8d0298b2-e8e2-4488-aeda-d14f67541cfb" />

## Prerequisites

### Software Requirements

- Python 3.7+
- kubectl configured with access to a Kubernetes cluster (e.g. create a cluster with `kind` or `minikube`)
- Access to VPN-AWS
- Required Python packages:

  ```bash
  pip install requests rich
  ```

### Kubernetes Cluster

- A running Kubernetes cluster with at least one worker node
- kubectl configured and authenticated
- Sufficient permissions to create/delete pods, deployments, and apply taints

### LLM API Access

- Access to the SolarWinds LLM Gateway (or modify the API configuration for your LLM service)
- Valid JWT token for authentication (ssp dev bot will give you the token)

## Installation

1. Clone or download the script files
2. Install Python dependencies:

   ```bash
   pip install -r requirements.txt
   ```

   Or install manually:

   ```bash
   pip install requests rich
   ```

3. Update the API configuration in `pods.py`:

   ```python
   LLM_API_URL = "your-llm-api-endpoint"
   HEADERS = {
       "Content-Type": "application/json",
       "Authorization": "Bearer <your-jwt-token>"
   }
   ```

## Usage

### Basic Usage

```bash
python pods.py
```

The script will run through all 10 scenarios automatically, displaying:

- Scenario description
- Applied Kubernetes manifest
- Pod identification
- LLM classification of the failure
- Detailed diagnostic context
- AI-generated remediation plan

After each scenario, the script pauses and waits for user input to continue to the next scenario.

## Failure Scenarios

### 1. Insufficient CPU (`1_insufficient_cpu.yaml`)

- **Issue**: Pod requests more CPU than available on any node
- **State**: Pending
- **Classification**: SchedulingFailure

### 2. Taint Toleration (`2_taint_toleration.yaml`)

- **Issue**: Pod lacks toleration for node taint
- **State**: Pending
- **Classification**: SchedulingFailure

### 3. Node Selector (`3_node_selector.yaml`)

- **Issue**: Pod's nodeSelector references non-existent node label
- **State**: Pending
- **Classification**: SchedulingFailure

### 4. Invalid Image Name (`4_invalid_image_name.yaml`)

- **Issue**: Typo in container image name
- **State**: ImagePullBackOff
- **Classification**: ImagePullFailure

### 5. Registry authentication problem was removed

### 6. Missing ConfigMap (`6_missing_configmap.yaml`)

- **Issue**: Pod references non-existent ConfigMap
- **State**: CreateContainerConfigError
- **Classification**: ConfigurationFailure

### 7. Failing Init Container (`7_failing_init_container.yaml`)

- **Issue**: Init container exits with error
- **State**: Init:CrashLoopBackOff
- **Classification**: InitializationFailure

### 8. App Logic Error (`8_app_logic_error.yaml`)

- **Issue**: Application code crashes on startup
- **State**: CrashLoopBackOff
- **Classification**: RuntimeCrash

### 9. OOMKilled (`9_oomkilled.yaml`)

- **Issue**: Container exceeds memory limit
- **State**: OOMKilled
- **Classification**: RuntimeCrash

### 10. Bad Liveness Probe (`10_bad_liveness_probe.yaml`)

- **Issue**: Misconfigured liveness probe kills healthy pod
- **State**: CrashLoopBackOff
- **Classification**: RuntimeCrash

### 11. Bad Readiness Probe (`11_bad_readiness_probe.yaml`)

- **Issue**: Failing readiness probe prevents traffic routing
- **State**: Running (but not ready)
- **Classification**: HealthCheckFailure

## How it works

### 1. Classification phase

The LLM first analyzes the pod's current state using `kubectl get pod` output to classify the failure type into one of six categories:

- SchedulingFailure
- ImagePullFailure
- ConfigurationFailure
- InitializationFailure
- RuntimeCrash
- HealthCheckFailure

### 2. Context collection phase

Based on the classification, the script intelligently collects relevant diagnostic information:

- **SchedulingFailure**: Node descriptions and resource availability
- **ConfigurationFailure**: Available ConfigMaps in namespace
- **InitializationFailure**: Init container logs
- **RuntimeCrash**: Container logs
- **HealthCheckFailure**: Service endpoints

### 3. Analysis phase

The collected context is sent to the LLM for detailed analysis, which provides:

- Root cause identification
- Detailed technical analysis
- Step-by-step remediation plan
- Corrected YAML manifests or commands

## File structure

```text
remediation/
├── pods.py                          # Main script
├── README.md                        # This file
└── scenarios/                       # Kubernetes manifests
    ├── 1_insufficient_cpu.yaml
    ├── 2_taint_toleration.yaml
    ├── 3_node_selector.yaml
    ├── 4_invalid_image_name.yaml
    ├── 6_missing_configmap.yaml
    ├── 7_failing_init_container.yaml
    ├── 8_app_logic_error.yaml
    ├── 9_oomkilled.yaml
    ├── 10_bad_liveness_probe.yaml
    └── 11_bad_readiness_probe.yaml
```

## Contributing

To add new scenarios:

1. Create a new YAML manifest in the `scenarios/` directory
2. Add scenario configuration to the `SCENARIOS` dictionary
3. Update the context collection logic in `perceive_context()` if needed

## License

This tool is provided as-is for educational and demonstration purposes.

## Disclaimer

This script creates and deletes Kubernetes resources. NEVER use in a production environment.
