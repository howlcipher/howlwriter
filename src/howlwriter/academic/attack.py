"""ATT&CK Semantic Grounding & Official Technique Source Model.

Provides deep semantic validation for MITRE ATT&CK techniques, verifying not
merely that an identifier exists, but that:
1. Identifier exists in the official ATT&CK taxonomy
2. Official technique/sub-technique name matches
3. ATT&CK tactic is compatible
4. Described behavior actually belongs to that technique
5. Sub-technique is correct
6. Current official source supports the mapping

Disallows synthetic catch-all blobs and catches regressions such as:
- Timestomping (T1070.006) folded into File Deletion (T1070.004)
- Volume shadow-copy deletion (T1490) folded into Encryption (T1486)
- Pastebin/text storage (T1567.003) folded into Code Repository (T1567.001)
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from howlwriter.domain.serialization import DataClassSerializationMixin
from howlwriter.domain.source import DEPTH_FULL_TEXT, DEPTH_PARTIAL_TEXT, Source


@dataclass
class AttackTechniqueRecord(DataClassSerializationMixin):
    """Authoritative official MITRE ATT&CK technique record."""

    technique_id: str
    name: str
    tactics: list[str]
    url: str
    version: str | None = None
    last_modified: str | None = None
    retrieved_at: str | None = None
    is_subtechnique: bool = False
    parent_technique_id: str | None = None
    supported_behaviors: list[str] = field(default_factory=list)
    excluded_behaviors: dict[str, str] = field(default_factory=dict)
    supported_semantic_facts: list[str] = field(default_factory=list)


@dataclass
class AttackSemanticValidation(DataClassSerializationMixin):
    """Granular semantic evaluation of an ATT&CK technique mapping."""

    technique_id: str
    identifier_exists: bool = False
    name_matches: bool = False
    tactic_matches: bool = False
    behavior_matches: bool = False
    sub_technique_correct: bool = True
    source_supported: bool = False
    unmapped_behaviors: list[str] = field(default_factory=list)
    suggested_techniques: list[str] = field(default_factory=list)
    semantic_verdict: str = "FAIL"  # "PASS" | "FAIL"
    notes: str = ""

    @property
    def is_verified(self) -> bool:
        return self.semantic_verdict == "PASS"


# Official Knowledge Base of Technique Records
_OFFICIAL_ATTACK_RECORDS: dict[str, AttackTechniqueRecord] = {
    "T1070.004": AttackTechniqueRecord(
        technique_id="T1070.004",
        name="Indicator Removal: File Deletion",
        tactics=["Defense Evasion"],
        url="https://attack.mitre.org/techniques/T1070/004/",
        version="2.1",
        last_modified="2024-03-28",
        is_subtechnique=True,
        parent_technique_id="T1070",
        supported_behaviors=[
            "file deletion",
            "delete files",
            "unlinking files",
            "sdelete",
            "rm ",
            "removing indicators",
            "erasing artifacts",
        ],
        excluded_behaviors={
            "timestomp": "T1070.006",
            "timestamp": "T1070.006",
            "modify creation time": "T1070.006",
            "clear event log": "T1070.001",
            "clearing event log": "T1070.001",
            "clear command history": "T1070.003",
        },
        supported_semantic_facts=[
            "Adversaries delete files generated during intrusion to remove forensic evidence.",
            "Covers utilities like sdelete, rm, or APIs like DeleteFile.",
            "Does not cover modifying file timestamps, which is T1070.006.",
        ],
    ),
    "T1070.006": AttackTechniqueRecord(
        technique_id="T1070.006",
        name="Indicator Removal: Timestomp",
        tactics=["Defense Evasion"],
        url="https://attack.mitre.org/techniques/T1070/006/",
        version="1.1",
        last_modified="2023-10-15",
        is_subtechnique=True,
        parent_technique_id="T1070",
        supported_behaviors=[
            "timestomp",
            "timestomping",
            "modifying timestamp",
            "altering file timestamps",
            "timestamp manipulation",
            "touch -r",
        ],
        excluded_behaviors={
            "file deletion": "T1070.004",
            "deleting files": "T1070.004",
        },
        supported_semantic_facts=[
            "Adversaries modify file time attributes (MAC timestamps) to blend in with legitimate files.",
        ],
    ),
    "T1486": AttackTechniqueRecord(
        technique_id="T1486",
        name="Data Encrypted for Impact",
        tactics=["Impact"],
        url="https://attack.mitre.org/techniques/T1486/",
        version="2.0",
        last_modified="2024-04-10",
        is_subtechnique=False,
        supported_behaviors=[
            "data encryption",
            "encrypting victim data",
            "encrypt files",
            "encrypt",
            "ransomware encryption",
            "locking files",
        ],
        excluded_behaviors={
            "shadow copy": "T1490",
            "shadow copies": "T1490",
            "vssadmin delete": "T1490",
            "inhibit recovery": "T1490",
            "disable recovery": "T1490",
            "delete backups": "T1490",
        },
        supported_semantic_facts=[
            "Adversaries encrypt data on target systems to interrupt system availability.",
            "Does not include destroying or deleting recovery mechanisms (shadow copies), which is T1490.",
        ],
    ),
    "T1490": AttackTechniqueRecord(
        technique_id="T1490",
        name="Inhibit System Recovery",
        tactics=["Impact"],
        url="https://attack.mitre.org/techniques/T1490/",
        version="2.1",
        last_modified="2024-03-30",
        is_subtechnique=False,
        supported_behaviors=[
            "shadow copy",
            "shadow copies",
            "vssadmin",
            "delete shadows",
            "inhibit recovery",
            "disable system recovery",
            "wbadmin delete",
            "bcedit /set",
        ],
        excluded_behaviors={
            "file encryption": "T1486",
            "encrypting data": "T1486",
        },
        supported_semantic_facts=[
            "Adversaries delete or modify system backups and volume shadow copies to prevent recovery.",
        ],
    ),
    "T1567.001": AttackTechniqueRecord(
        technique_id="T1567.001",
        name="Exfiltration Over Web Service: Exfiltration to Code Repository",
        tactics=["Exfiltration"],
        url="https://attack.mitre.org/techniques/T1567/001/",
        version="1.1",
        last_modified="2023-09-12",
        is_subtechnique=True,
        parent_technique_id="T1567",
        supported_behaviors=[
            "github",
            "gitlab",
            "bitbucket",
            "git push",
            "code repository",
            "public repository",
        ],
        excluded_behaviors={
            "pastebin": "T1567.003",
            "ghostbin": "T1567.003",
            "text storage": "T1567.003",
            "cloud storage": "T1567.002",
            "mega.nz": "T1567.002",
            "dropbox": "T1567.002",
            "google drive": "T1567.002",
        },
        supported_semantic_facts=[
            "Adversaries exfiltrate data to public or private commercial code repositories like GitHub or GitLab.",
            "Does not cover text-storage/paste sites, which belong to T1567.003.",
        ],
    ),
    "T1567.003": AttackTechniqueRecord(
        technique_id="T1567.003",
        name="Exfiltration Over Web Service: Exfiltration to Text Storage Sites",
        tactics=["Exfiltration"],
        url="https://attack.mitre.org/techniques/T1567/003/",
        version="1.0",
        last_modified="2023-09-12",
        is_subtechnique=True,
        parent_technique_id="T1567",
        supported_behaviors=[
            "pastebin",
            "ghostbin",
            "text storage site",
            "paste site",
            "rentry",
        ],
        excluded_behaviors={
            "github": "T1567.001",
            "code repository": "T1567.001",
        },
        supported_semantic_facts=[
            "Adversaries exfiltrate data to text-storage sites like Pastebin.",
        ],
    ),
    "T1567.002": AttackTechniqueRecord(
        technique_id="T1567.002",
        name="Exfiltration Over Web Service: Exfiltration to Cloud Storage",
        tactics=["Exfiltration"],
        url="https://attack.mitre.org/techniques/T1567/002/",
        version="1.2",
        last_modified="2023-11-20",
        is_subtechnique=True,
        parent_technique_id="T1567",
        supported_behaviors=[
            "cloud storage",
            "mega.nz",
            "rclone",
            "dropbox",
            "google drive",
            "onedrive",
            "s3 exfil",
        ],
        excluded_behaviors={
            "pastebin": "T1567.003",
            "github": "T1567.001",
        },
        supported_semantic_facts=[
            "Adversaries exfiltrate data to external cloud storage services.",
        ],
    ),
    "T1003.001": AttackTechniqueRecord(
        technique_id="T1003.001",
        name="OS Credential Dumping: LSASS Memory",
        tactics=["Credential Access"],
        url="https://attack.mitre.org/techniques/T1003/001/",
        is_subtechnique=True,
        parent_technique_id="T1003",
        supported_behaviors=["lsass", "credential dumping", "in-memory credential", "dump", "procdump", "mimikatz"],
    ),
    "T1190": AttackTechniqueRecord(
        technique_id="T1190",
        name="Exploit Public-Facing Application",
        tactics=["Initial Access"],
        url="https://attack.mitre.org/techniques/T1190/",
        supported_behaviors=["exploit", "vulnerability", "public-facing", "ssl-vpn", "web application"],
    ),
    "T1059.001": AttackTechniqueRecord(
        technique_id="T1059.001",
        name="Command and Scripting Interpreter: PowerShell",
        tactics=["Execution"],
        url="https://attack.mitre.org/techniques/T1059/001/",
        is_subtechnique=True,
        parent_technique_id="T1059",
        supported_behaviors=["powershell", "script block", "powershell.exe", "pwsh"],
    ),
    "T1087.002": AttackTechniqueRecord(
        technique_id="T1087.002",
        name="Account Discovery: Domain Account",
        tactics=["Discovery"],
        url="https://attack.mitre.org/techniques/T1087/002/",
        is_subtechnique=True,
        parent_technique_id="T1087",
        supported_behaviors=["domain account", "ldap", "adfind", "net user /domain", "bloodhound"],
    ),
    "T1021.002": AttackTechniqueRecord(
        technique_id="T1021.002",
        name="Remote Services: SMB/Windows Admin Shares",
        tactics=["Lateral Movement"],
        url="https://attack.mitre.org/techniques/T1021/002/",
        is_subtechnique=True,
        parent_technique_id="T1021",
        supported_behaviors=["smb", "admin shares", "psexec", "c$", "admin$"],
    ),
    "T1595.002": AttackTechniqueRecord(
        technique_id="T1595.002",
        name="Active Scanning: Vulnerability Scanning",
        tactics=["Reconnaissance"],
        url="https://attack.mitre.org/techniques/T1595/002/",
        is_subtechnique=True,
        parent_technique_id="T1595",
        supported_behaviors=["vulnerability scanning", "shodan", "syn scan", "active scanning"],
    ),
    "T1566.002": AttackTechniqueRecord(
        technique_id="T1566.002",
        name="Phishing: Spearphishing Link",
        tactics=["Initial Access"],
        url="https://attack.mitre.org/techniques/T1566/002/",
        is_subtechnique=True,
        parent_technique_id="T1566",
        supported_behaviors=["spearphishing link", "evilginx", "aitm", "phishing url"],
    ),
    "T1543.003": AttackTechniqueRecord(
        technique_id="T1543.003",
        name="Create or Modify System Process: Windows Service",
        tactics=["Persistence", "Privilege Escalation"],
        url="https://attack.mitre.org/techniques/T1543/003/",
        is_subtechnique=True,
        parent_technique_id="T1543",
        supported_behaviors=["windows service", "sc.exe", "service installation", "service creation"],
    ),
    "T1560.001": AttackTechniqueRecord(
        technique_id="T1560.001",
        name="Archive Collected Data: Archive via Utility",
        tactics=["Collection"],
        url="https://attack.mitre.org/techniques/T1560/001/",
        is_subtechnique=True,
        parent_technique_id="T1560",
        supported_behaviors=["7-zip", "7z", "archive via utility", "winrar", "zip compression"],
    ),
    "T1071.001": AttackTechniqueRecord(
        technique_id="T1071.001",
        name="Application Layer Protocol: Web Protocols",
        tactics=["Command and Control"],
        url="https://attack.mitre.org/techniques/T1071/001/",
        is_subtechnique=True,
        parent_technique_id="T1071",
        supported_behaviors=["web protocols", "https beaconing", "http c2", "tls ja3"],
    ),
    "T1041": AttackTechniqueRecord(
        technique_id="T1041",
        name="Exfiltration Over C2 Channel",
        tactics=["Exfiltration"],
        url="https://attack.mitre.org/techniques/T1041/",
        supported_behaviors=["exfiltration over c2", "c2 exfil", "channel exfiltration"],
    ),
    "T1078.004": AttackTechniqueRecord(
        technique_id="T1078.004",
        name="Valid Accounts: Cloud Accounts",
        tactics=["Defense Evasion", "Initial Access", "Persistence", "Privilege Escalation"],
        url="https://attack.mitre.org/techniques/T1078/004/",
        is_subtechnique=True,
        parent_technique_id="T1078",
        supported_behaviors=["cloud accounts", "iam keys", "aws credentials", "cloud admin"],
    ),
    "T1098": AttackTechniqueRecord(
        technique_id="T1098",
        name="Account Manipulation",
        tactics=["Persistence", "Privilege Escalation"],
        url="https://attack.mitre.org/techniques/T1098/",
        supported_behaviors=["account manipulation", "iam policy", "attach-user-policy", "modify permissions"],
    ),
    "T1491.002": AttackTechniqueRecord(
        technique_id="T1491.002",
        name="Defacement: External Defacement",
        tactics=["Impact"],
        url="https://attack.mitre.org/techniques/T1491/002/",
        is_subtechnique=True,
        parent_technique_id="T1491",
        supported_behaviors=["defacement", "external defacement", "s3 website index replacement"],
    ),
    "T1489": AttackTechniqueRecord(
        technique_id="T1489",
        name="Service Stop",
        tactics=["Impact"],
        url="https://attack.mitre.org/techniques/T1489/",
        supported_behaviors=["service stop", "stopinstances", "systemctl stop", "terminate service"],
    ),
}


class AttackKnowledgeBase:
    """Provides authoritative technique records without copying massive web content."""

    def __init__(self, custom_records: dict[str, AttackTechniqueRecord] | None = None) -> None:
        self._records = dict(_OFFICIAL_ATTACK_RECORDS)
        if custom_records:
            self._records.update(custom_records)

    def get_record(self, technique_id: str) -> AttackTechniqueRecord | None:
        return self._records.get(technique_id)

    def contains(self, technique_id: str) -> bool:
        return technique_id in self._records

    def register_record(self, record: AttackTechniqueRecord) -> None:
        self._records[record.technique_id] = record


def validate_attack_mapping(
    technique_id: str,
    context_text: str,
    *,
    claimed_name: str | None = None,
    claimed_tactic: str | None = None,
    sources: list[Source] | None = None,
    additional_grounding_texts: list[str] | None = None,
    kb: AttackKnowledgeBase | None = None,
    all_mapped_techniques: list[str] | None = None,
) -> AttackSemanticValidation:
    """Performs separate semantic validation across all ATT&CK mapping facets."""
    kb = kb or AttackKnowledgeBase()
    record = kb.get_record(technique_id)

    if record is None:
        # Check if ID exists anywhere in authoritative sources with substantive depth
        source_found = False
        if additional_grounding_texts:
            for g in additional_grounding_texts:
                if technique_id.lower() in g.lower():
                    source_found = True
                    break
        if not source_found and sources:
            for s in sources:
                if s.retrieved_text and technique_id.lower() in s.retrieved_text.lower():
                    if s.evidence_depth in (DEPTH_FULL_TEXT, DEPTH_PARTIAL_TEXT):
                        source_found = True
                        break
        return AttackSemanticValidation(
            technique_id=technique_id,
            identifier_exists=source_found,
            name_matches=False,
            tactic_matches=False,
            behavior_matches=False,
            sub_technique_correct=False,
            source_supported=source_found,
            semantic_verdict="FAIL",
            notes=f"Identifier {technique_id} is not present in authoritative ATT&CK records.",
        )

    # 1. Identifier exists
    identifier_exists = True

    # 2. Official name matches
    name_matches = True
    if claimed_name:
        rec_name_clean = re.sub(r"^[^:]+:\s*", "", record.name).lower()
        claimed_clean = re.sub(r"^[^:]+:\s*", "", claimed_name).lower()
        name_matches = (
            claimed_clean in record.name.lower()
            or rec_name_clean in claimed_name.lower()
            or claimed_clean == rec_name_clean
        )

    # 3. ATT&CK tactic is compatible
    tactic_matches = True
    if claimed_tactic:
        tactic_matches = any(
            claimed_tactic.lower() == t.lower() or claimed_tactic.lower() in t.lower()
            for t in record.tactics
        )

    # 4. Described behavior actually belongs to that technique
    context_lower = context_text.lower()
    behavior_matches = True
    if record.supported_behaviors:
        behavior_matches = any(sb.lower() in context_lower for sb in record.supported_behaviors)

    # 5. Check for unmapped/sibling behaviors that belong to other techniques
    unmapped: list[str] = []
    suggested: list[str] = []
    active_all = set(all_mapped_techniques or [])
    active_all.add(technique_id)

    for excluded_kw, target_tech in record.excluded_behaviors.items():
        if excluded_kw.lower() in context_lower:
            # If the target technique is NOT mapped in this context, it is an error
            if target_tech not in active_all:
                unmapped.append(excluded_kw)
                if target_tech not in suggested:
                    suggested.append(target_tech)
                behavior_matches = False

    # 6. Sub-technique check
    sub_technique_correct = True
    if "." in technique_id and not record.is_subtechnique:
        sub_technique_correct = False
    elif "." not in technique_id and record.is_subtechnique:
        sub_technique_correct = False

    # 7. Authoritative source support
    source_supported = False
    if additional_grounding_texts:
        for g in additional_grounding_texts:
            if technique_id.lower() in g.lower():
                source_supported = True
                break
    if not source_supported and sources:
        for s in sources:
            if s.retrieved_text and technique_id.lower() in s.retrieved_text.lower():
                if s.evidence_depth in (DEPTH_FULL_TEXT, DEPTH_PARTIAL_TEXT):
                    source_supported = True
                    break
    elif not sources and not additional_grounding_texts:
        # In standalone checks with KB, KB acts as authoritative source
        source_supported = True

    verdict = "PASS" if (
        identifier_exists
        and name_matches
        and tactic_matches
        and behavior_matches
        and sub_technique_correct
        and source_supported
    ) else "FAIL"

    notes = ""
    if unmapped:
        notes = (
            f"Context contains behaviors ({', '.join(unmapped)}) that belong to "
            f"other techniques ({', '.join(suggested)}), but they were unmapped."
        )
    elif not behavior_matches:
        notes = f"Described behavior in context does not match supported behaviors for {technique_id}."
    elif not name_matches:
        notes = f"Claimed name '{claimed_name}' does not match official name '{record.name}'."
    elif not tactic_matches:
        notes = f"Claimed tactic '{claimed_tactic}' is incompatible with official tactics {record.tactics}."

    return AttackSemanticValidation(
        technique_id=technique_id,
        identifier_exists=identifier_exists,
        name_matches=name_matches,
        tactic_matches=tactic_matches,
        behavior_matches=behavior_matches,
        sub_technique_correct=sub_technique_correct,
        source_supported=source_supported,
        unmapped_behaviors=unmapped,
        suggested_techniques=suggested,
        semantic_verdict=verdict,
        notes=notes,
    )
