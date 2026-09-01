# CYBR 601 Laboratory Report: Cloud and Kubernetes Attack Chain Analysis

## Introduction

Enterprise adoption of cloud-native architectures and container orchestrators like Kubernetes has shifted the threat landscape of modern IT infrastructure. While cloud platforms provide substantial scalability and operational flexibility, they introduce multi-layered attack surfaces that bypass traditional perimeter defenses (Sreedevi & Barathi, 2026). Instead of relying primarily on network firewalls, cloud boundaries depend on identity and access management (IAM) frameworks, software-defined networks, multi-tenant isolation controls, and workload admission policies (BinSaeedan & Alqahtani, 2025).

Adversaries targeting cloud environments routinely exploit the relationships between cloud management APIs, cluster control planes, and running containers. A single exposed credential or misconfiguration can trigger multi-stage intrusions spanning separate operational layers. Common entry vectors include exposed static credentials in source control, over-permissive role-based access control (RBAC) bindings in Kubernetes clusters, and spear-phishing campaigns targeting engineering staff (Sreedevi & Barathi, 2026).

This report analyzes three realistic attack chains against an enterprise cloud and Kubernetes environment:
1. Leaked cloud management credentials enabling control plane discovery and data exfiltration.
2. Kubernetes RBAC misconfiguration leading to container breakout and node takeover.
3. Spear-phishing against developer endpoints leading to internal network pivoting and CI/CD pipeline poisoning.

Each attack chain is examined across its sequential execution stages mapped to MITRE ATT&CK tactics, accompanied by relevant offensive and defensive tools, detection telemetry, and monitoring strategies. The report concludes by synthesizing cross-chain defensive themes to define a defense-in-depth framework for cloud and container infrastructure.

## Attack Chain One: Leaked Cloud Credentials

### Attack Scenario and Progression

This scenario begins when a developer accidentally commits long-lived cloud IAM access keys to a public source code repository during a software release. The compromised credentials belong to an automation service account configured with broad administrative and provisioning privileges.

```
[Stage 1: Credential Exposure] ---> [Stage 2: Reconnaissance] ---> [Stage 3: Privilege Escalation] ---> [Stage 4: Lateral Movement] ---> [Stage 5: Data Exfiltration]
    (Initial Access / Recon)            (Cloud Discovery)                 (IAM Policy Modification)             (Cluster Control Plane Ingress)       (Exfiltration / Impact)
```

1. **Stage 1: Initial Access and Credential Exposure (Tactics: Initial Access, Credential Access).** Automated secret-scraping tools monitor public repositories and detect the exposed access key ID and secret access key. The attacker obtains these credentials passively, without generating network traffic against the target organization.
2. **Stage 2: Discovery and Cloud Service Enumeration (Tactic: Discovery).** Authenticating through the provider's management API with the stolen keys, the adversary queries account identity details, active Virtual Private Clouds (VPCs), managed Kubernetes clusters, object storage repositories, and database instances.
3. **Stage 3: Privilege Escalation and Persistence (Tactics: Privilege Escalation, Persistence).** Because the compromised IAM policy permits policy updates and role attachments, the attacker creates a secondary administrator account and attaches administrative policies. This provides persistent access if the initial leaked key is revoked.
4. **Stage 4: Lateral Movement into Managed Infrastructure (Tactic: Lateral Movement).** Using administrative privileges, the attacker generates access credentials for the managed Kubernetes control plane and updates cluster authentication mappings. This grants direct remote control over cluster workloads from an external IP address.
5. **Stage 5: Exfiltration and Impact (Tactics: Exfiltration, Impact).** Operating with administrative rights, the adversary locates private object storage buckets containing database backups, customer records, and application assets. The attacker transfers this data over HTTPS to an external, adversary-controlled storage location.

### Tooling Overview

* **Attacker Tooling:** Secret scanners (such as TruffleHog and GitLeaks) for repository harvesting; official cloud provider CLIs (AWS CLI, Azure CLI, gcloud) for direct API interactions; cloud exploitation frameworks (such as Pacu and ScoutSuite) to automate enumeration and policy escalation.
* **Defender Tooling:** Pre-commit hooks and repository scanning tools to block secrets before commits are pushed; Cloud Security Posture Management (CSPM) platforms to flag overly broad IAM policies; cloud audit log analyzers and SIEM platforms for real-time API monitoring.

### Telemetry and Detection Opportunities

* **Management Plane API Audit Logs:** Cloud audit logs record authenticated API requests. Key indicators include API calls originating from unexpected geographic regions or unapproved ASNs, rapid bursts of enumeration commands (`Get*`, `List*`, `Describe*`), and policy modification events that attach administrator permissions or create new access keys.
* **Identity and Authentication Telemetry:** Identity provider logs highlight anomalous sessions, such as impossible travel alerts, concurrent logins across distant regions, and programmatic API access outside normal working hours.
* **Storage and Network Telemetry:** Object storage logs and VPC flow records capture abnormal data transfer activity, including abrupt spikes in egress bandwidth and bulk download operations targeting rarely accessed archival buckets.

## Attack Chain Two: Kubernetes RBAC Privilege Escalation

### Attack Scenario and Progression

Here, an attacker exploits an unauthenticated remote code execution vulnerability in an internet-facing web application running inside a Kubernetes pod. While the application runs in an unprivileged container, its assigned ServiceAccount holds overly broad RBAC permissions, specifically the ability to create pods and bind roles within the namespace.

```
[Stage 1: Initial Pod Breach] ---> [Stage 2: Token Harvesting] ---> [Stage 3: RBAC Enumeration] ---> [Stage 4: Privileged Pod Creation] ---> [Stage 5: Host Node Takeover]
   (Exploit Web App RCE)            (Extract ServiceAccount)         (SelfSubjectAccessReview)          (Mount Host Root Filesystem)            (chroot Breakout & Pivot)
```

1. **Stage 1: Execution and Token Extraction (Tactics: Execution, Credential Access).** After exploiting the web application RCE, the attacker accesses the container filesystem. By default, Kubernetes mounts the pod's ServiceAccount JWT and Certificate Authority (CA) certificate at `/var/run/secrets/kubernetes.io/serviceaccount/`, where the attacker extracts them.
2. **Stage 2: Discovery and RBAC Enumeration (Tactic: Discovery).** Using the harvested token, the attacker communicates directly with the internal API server (`kubernetes.default.svc`). Submitting `SelfSubjectAccessReview` queries reveals that the token can list, create, and modify pod specifications within the current namespace.
3. **Stage 3: Privilege Escalation via Pod Specification (Tactic: Privilege Escalation).** The attacker creates a malicious pod manifest configured for host breakout. The manifest requests a privileged container context (`privileged: true`), enables host process namespace sharing (`hostPID: true`), and mounts the worker node's root filesystem (`/`) to an internal container directory via `hostPath`.
4. **Stage 4: Defense Evasion and Container Breakout (Tactics: Defense Evasion, Execution).** The Kubernetes API server validates the request against RBAC rules and schedules the pod onto a worker node. Once the container starts, the attacker opens an interactive shell and executes `chroot` against the mounted host root filesystem, gaining root control over the host node operating system.
5. **Stage 5: Lateral Movement and Multi-Tenant Compromise (Tactics: Lateral Movement, Persistence).** From the compromised node, the attacker extracts local kubelet credentials, inspects adjacent pods running in other namespaces on the shared node, and retrieves co-located environment variables and secrets. This compromise of multi-tenant boundaries exposes neighboring workloads on the shared infrastructure (BinSaeedan & Alqahtani, 2025).

### Tooling Overview

* **Attacker Tooling:** In-container networking utilities (`curl`, `wget`); `kubectl`; container penetration testing and breakout suites (such as `kube-hunter`, `Peirates`, `amicontained`, and `CDK`) to automate token retrieval, RBAC queries, and filesystem mounts.
* **Defender Tooling:** Kubernetes Admission Controllers (Open Policy Agent Gatekeeper, Kyverno) enforcing Pod Security Standards; cluster configuration auditors (`kube-bench`); kernel runtime monitoring agents (Falco, Tracee) leveraging eBPF.

### Telemetry and Detection Opportunities

* **Kubernetes API Audit Logs:** API server audit records capture resource modifications. High-priority detection signals include pod creation requests specifying `privileged: true`, `hostPath` volume mounts, or `hostPID: true`, alongside repeated `SelfSubjectAccessReview` queries from workload IP addresses.
* **Kernel and Host Runtime Telemetry:** Runtime sensors using eBPF inspect system call activity directly on worker nodes. Key indicators include interactive shell spawns inside non-interactive workloads, `chroot` or `setns` invocations, and unauthorized reads or writes to host paths like `/etc/kubernetes/` or `/etc/shadow`.
* **Internal Network Telemetry:** Container Network Interface (CNI) telemetry and network policy monitoring can detect unexpected direct HTTP/HTTPS connections from workload pods to the cluster API server endpoint.

## Attack Chain Three: Phishing-Based Lateral Movement

### Attack Scenario and Progression

During this campaign, an attacker targets senior DevOps and infrastructure engineers with spear-phishing emails. The goal is to compromise an authenticated developer workstation, capture credentials and session tokens, and leverage internal network access to pivot into the production cloud VPC and tamper with CI/CD deployment pipelines (Sreedevi & Barathi, 2026).

```
[Stage 1: Spear-Phishing Email] ---> [Stage 2: Workstation Compromise] ---> [Stage 3: Bastion Host Pivoting] ---> [Stage 4: Internal VPC Recon] ---> [Stage 5: CI/CD Pipeline Poisoning]
     (Malicious Attachment/Lure)           (Harvest SSH & Cloud Tokens)          (Authenticate via Enterprise VPN)        (Discover Private Registries)            (Inject Malicious Code)
```

1. **Stage 1: Initial Access via Spear-Phishing (Tactic: Initial Access).** The adversary delivers a spear-phishing email disguised as an urgent IT security notification regarding cloud credentials. The email links to a credential harvesting proxy or includes an attachment with obfuscated macro code (Sreedevi & Barathi, 2026).
2. **Stage 2: Execution and Credential Harvesting (Tactics: Execution, Credential Access).** Once the recipient executes the lure, a secondary payload executes on the endpoint. The attacker dumps local process memory and reads local configuration files to harvest enterprise SSO session tokens, private SSH keys, cloud CLI configurations, and Kubernetes cluster profiles stored on the workstation.
3. **Stage 3: Lateral Movement to Bastion Hosts (Tactic: Lateral Movement).** Using the stolen credentials and active session tokens, the adversary authenticates to the corporate VPN. From the VPN entry point, the attacker initiates an SSH session to an internal cloud bastion host that connects corporate IT with the production cloud VPC.
4. **Stage 4: Discovery and Internal Infrastructure Reconnaissance (Tactic: Discovery).** From the bastion host, the attacker scans internal subnets to map reachable services. This reconnaissance identifies private container registries, internal administrative portals, and build servers isolated from the public internet.
5. **Stage 5: Privilege Escalation and Persistence via CI/CD Poisoning (Tactics: Privilege Escalation, Persistence).** The attacker uses compromised developer tokens to modify repository deployment pipelines. By adding a malicious build step, automated CI/CD jobs inject an obfuscated backdoor into production container images, establishing long-term persistence across deployed cloud workloads (Sreedevi & Barathi, 2026).

### Tooling Overview

* **Attacker Tooling:** Phishing frameworks (such as Evilginx and GoPhish); memory dumping utilities; network tunneling tools (such as Chisel and dynamic SSH forwarding) to route traffic through internal bastions.
* **Defender Tooling:** Machine-learning email security gateways with vectorization and ensemble classifiers (Sreedevi & Barathi, 2026); Endpoint Detection and Response (EDR) agents; Network Detection and Response (NDR) sensors; Privileged Access Management (PAM) systems enforcing session recording and just-in-time access.

### Telemetry and Detection Opportunities

* **Inbound Email Telemetry:** Parsing email metadata and message content with natural language vectorization and machine-learning models provides early detection. Classifiers including Random Forest, K-Nearest Neighbors (KNN), Support Vector Machines (SVM), XGBoost, LightGBM, and ensemble voting models can flag phishing patterns and quarantine malicious messages before delivery (Sreedevi & Barathi, 2026).
* **Endpoint Telemetry:** Workstation EDR agents record process lineage, memory injection attempts, and unauthorized access to directories like `~/.ssh/`, `~/.aws/`, and `~/.kube/`.
* **Authentication and Network Access Logs:** VPN and bastion logs record suspicious logins, such as impossible travel indicators, concurrent sessions from unusual IP addresses, and unexpected SSH commands from developer endpoints.
* **CI/CD and Repository Audit Logs:** Version control and pipeline telemetry highlight modified build scripts, unauthorized pipeline configuration commits, and builds triggered outside standard deployment schedules.

## Cross-Chain Defensive Themes

Comparing these attack chains highlights recurring defensive priorities across cloud environments. Security requires a coordinated defense-in-depth model encompassing identity governance, workload controls, tenant isolation, machine-learning-assisted detection, and centralized observability.

```
+---------------------------------------------------------------------------------------------------+
|                                   CROSS-CHAIN DEFENSIVE ARCHITECTURE                              |
+---------------------------------+---------------------------------+-------------------------------+
|  1. IDENTITY & ACCESS (IAM/RBAC)|  2. WORKLOAD HARDENING & POLICY |  3. ML & ANOMALY DETECTION    |
|  - Ephemeral short-lived tokens |  - Admission control (Gatekeeper|  - Ensemble ML email filters  |
|  - Elimination of static keys   |  - Read-only root filesystems   |  - Real-time alert generation |
|  - Strict least-privilege RBAC  |  - Block privileged containers  |  - Dynamic behavioral baselines|
+---------------------------------+---------------------------------+-------------------------------+
|  4. MULTI-TENANT ISOLATION      |  5. UNIFIED AUDIT OBSERVABILITY |  6. RESILIENCE & AVAILABILITY |
|  - Secure resource allocation   |  - Cloud management audit logs  |  - Defensive traffic modeling |
|  - Kernel namespace boundaries  |  - Kubernetes API server audit  |  - Anti-DDoS rate-limiting    |
|  - Pod-to-pod network policies  |  - eBPF host runtime telemetry  |  - Automated incident response|
+---------------------------------+---------------------------------+-------------------------------+
```

### 1. Identity Governance and Least Privilege

Identity serves as the primary security perimeter in cloud architectures. Organizations should replace long-lived static API keys with short-lived, assumed IAM roles protected by multi-factor authentication. Within Kubernetes clusters, RBAC policies must avoid wildcard permissions (`*`) and restrict administrative verbs (`create`, `bind`, `escalate`) on critical API resources. Furthermore, pods should not mount ServiceAccount tokens unless specifically required (`automountServiceAccountToken: false`).

### 2. Workload Hardening and Policy Enforcement

Workloads in container environments should be treated as untrusted. Admission controllers such as Open Policy Agent Gatekeeper or Kyverno can enforce policies that prohibit privileged containers, block `hostPath` volume mounts, disable host namespace sharing (`hostPID`, `hostNetwork`), and require read-only root filesystems. Pod network policies should implement a default-deny posture to restrict egress traffic strictly to approved endpoints.

### 3. Multi-Tenant Isolation and Resource Governance

When diverse workloads share compute infrastructure, maintaining strong container boundaries prevents lateral movement and cross-tenant data exposure. Structured resource allocation and isolation techniques, including particle swarm optimization and hardened virtualization boundaries, help prevent multitenancy attacks and maintain workload separation (BinSaeedan & Alqahtani, 2025). Additionally, infrastructure resilience requires proactive defenses against resource exhaustion and distributed denial-of-service threats to protect shared cluster availability (Iyengar & Ganapathy, 2015).

### 4. Multi-Layer Machine Learning and Anomaly Detection

Machine learning models provide real-time visibility across large telemetry volumes. In email security, feature vectorization paired with classifiers (such as Random Forest, KNN, SVM, XGBoost, and LightGBM) integrated through ensemble voting improves detection rates and minimizes false positives when identifying malicious messages (Sreedevi & Barathi, 2026). Similar behavioral anomaly detection models can be applied to cloud management API activity to uncover suspicious administrative operations.

### 5. Unified Telemetry and Correlated Observability

Defending cloud infrastructure requires aggregating telemetry across disparate layers into a unified SIEM or SOAR platform. Correlating cloud management API logs, Kubernetes audit events, eBPF system call traces, and endpoint telemetry allows analysts to detect multi-stage attack chains that might otherwise appear benign when viewed in isolation.

## Conclusion

Modern cloud and Kubernetes deployments eliminate traditional perimeter assumptions. As demonstrated across these three scenarios—credential leakage, container RBAC misconfigurations, and endpoint spear-phishing—adversaries consistently target trust boundaries between infrastructure layers to escalate privilege and access internal assets.

Mitigating these risks requires layered defensive engineering rather than isolated controls. Key operational priorities include enforcing ephemeral credentials and strict RBAC, applying admission policies to prevent privileged container execution, isolating multi-tenant workloads (BinSaeedan & Alqahtani, 2025), leveraging machine-learning models for anomaly detection (Sreedevi & Barathi, 2026), and safeguarding cluster availability (Iyengar & Ganapathy, 2015). Combining centralized API auditing, kernel-level eBPF instrumentation, and automated enforcement provides the visibility required to identify and intercept attacks across each stage of execution.

# References

BinSaeedan, W. M., & Alqahtani, N. M. (2025). Resource allocation based on particle swarm optimization for securing cloud environment against multitenancy attack. CRC Press. https://doi.org/10.1201/9781003614197-25
Iyengar, N. C. S. N., & Ganapathy, G. (2015). Chaotic theory based defensive mechanism against distributed denial of service attack in cloud computing environment. NADIA. https://doi.org/10.14257/ijsia.2015.9.9.18
Sreedevi, B., & Barathi, S. (2026). Email-Based privilege escalation attack detection in cloud environments using machine learning. IGI Global Scientific Publishing. https://doi.org/10.4018/979-8-3373-5992-2.ch004