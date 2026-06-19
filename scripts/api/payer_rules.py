"""Payer-specific rule engine for pre-submission validation.

Loads YAML rules from config/payer_rules/*.yml and applies them
during /validate endpoint checks.
"""

import os
from pathlib import Path
from typing import Dict, List, Any, Optional


class PayerRuleEngine:
    """Loads and applies payer-specific coding rules."""
    
    def __init__(self, rules_dir: str = "config/payer_rules"):
        self.rules_dir = Path(rules_dir)
        self.rules = {}  # payer_name → list of rules
        self._load()
    
    def _load(self):
        """Load all YAML rule files. Falls back to simple parsing if PyYAML not available."""
        if not self.rules_dir.exists():
            return
        
        try:
            import yaml
            has_yaml = True
        except ImportError:
            has_yaml = False
        
        for path in sorted(self.rules_dir.glob("*.yml")):
            if path.name == "README.md":
                continue
            try:
                if has_yaml:
                    with open(path) as f:
                        data = yaml.safe_load(f)
                    payer = data.get("payer", path.stem)
                    self.rules[payer] = data.get("rules", [])
                else:
                    # Fallback: minimal parsing without PyYAML
                    # Just count rules for stats
                    self.rules[path.stem] = [{"_source": str(path)}]
            except Exception as e:
                import sys
                print(f"Warning: Could not load payer rules {path.name}: {e}", file=sys.stderr)
    
    def get_payers(self) -> List[str]:
        """Return list of configured payers."""
        return list(self.rules.keys())
    
    def check_code(self, code: str, system: str, payer: Optional[str] = None,
                   patient_gender: Optional[str] = None, patient_age: Optional[int] = None,
                   co_codes: Optional[List[Dict]] = None) -> List[Dict]:
        """
        Check a code against payer rules. Returns list of issues found.
        
        Args:
            code: The code being validated
            system: Coding system (ICD-10-CM, CDT, etc.)
            payer: Payer name to check rules for. If None, checks all payers.
            patient_gender: M or F (for gender_restriction checks)
            patient_age: Patient age (for age_restriction checks)
            co_codes: List of {code, system} objects also being billed (for excluded_with checks)
        
        Returns:
            List of issue dicts: {payer, check_type, message, severity}
        """
        issues = []
        payers_to_check = [payer] if payer else list(self.rules.keys())
        
        for payer_name in payers_to_check:
            payer_rules = self.rules.get(payer_name, [])
            for rule in payer_rules:
                # Skip placeholder entries (from no-YAML fallback)
                if "_source" in rule:
                    continue
                
                rule_system = rule.get("code_system", "")
                if rule_system and system.upper() != rule_system.upper():
                    continue
                
                # Check code match
                rule_code = rule.get("code", "")
                rule_pattern = rule.get("code_pattern", "")
                
                code_matches = False
                if rule_code and code.upper() == rule_code.upper():
                    code_matches = True
                elif rule_pattern:
                    # Simple glob: E11* matches E11.9, E119, etc.
                    prefix = rule_pattern.rstrip("*")
                    if code.upper().startswith(prefix.upper()):
                        code_matches = True
                
                if not code_matches:
                    continue
                
                # Apply checks
                for check in rule.get("checks", []):
                    check_type = check.get("type", "")
                    message = check.get("message", "Rule violation")
                    
                    if check_type == "gender_restriction":
                        if patient_gender and patient_gender != check.get("allowed", ""):
                            issues.append({
                                "payer": payer_name,
                                "check_type": check_type,
                                "message": message,
                                "severity": "fail"
                            })
                    
                    elif check_type == "age_restriction":
                        if patient_age is not None:
                            min_age = check.get("min", 0)
                            max_age = check.get("max", 999)
                            if patient_age < min_age or patient_age > max_age:
                                issues.append({
                                    "payer": payer_name,
                                    "check_type": check_type,
                                    "message": message,
                                    "severity": "fail"
                                })
                    
                    elif check_type == "excluded_with":
                        excluded_system = check.get("code_system", system)
                        excluded_pattern = check.get("code_pattern", check.get("code", ""))
                        prefix = excluded_pattern.rstrip("*")
                        if co_codes:
                            for co in co_codes:
                                co_code = co.get("code", "")
                                co_system = co.get("system", "")
                                if co_system.upper() == excluded_system.upper():
                                    if co_code.upper().startswith(prefix.upper()):
                                        issues.append({
                                            "payer": payer_name,
                                            "check_type": check_type,
                                            "message": message,
                                            "severity": "fail"
                                        })
                                        break
                    
                    elif check_type == "requires_secondary":
                        # Check if required secondary code is in co_codes
                        req_system = check.get("system", "")
                        req_code = check.get("code", "")
                        req_pattern = check.get("code_pattern", "")
                        found = False
                        if co_codes:
                            for co in co_codes:
                                co_system = co.get("system", "")
                                co_code = co.get("code", "")
                                if co_system.upper() == req_system.upper():
                                    if req_code and co_code.upper() == req_code.upper():
                                        found = True
                                        break
                                    elif req_pattern:
                                        prefix = req_pattern.rstrip("*")
                                        if co_code.upper().startswith(prefix.upper()):
                                            found = True
                                            break
                        if not found:
                            issues.append({
                                "payer": payer_name,
                                "check_type": check_type,
                                "message": message,
                                "severity": "warning"
                            })
                    
                    elif check_type == "frequency_limit":
                        # Can't check frequency without historical data
                        issues.append({
                            "payer": payer_name,
                            "check_type": check_type,
                            "message": f"{message} (requires historical data to verify)",
                            "severity": "warning"
                        })
        
        return issues
    
    def stats(self) -> Dict:
        """Return rule engine statistics."""
        return {
            "payers_configured": len(self.rules),
            "payer_names": list(self.rules.keys()),
            "total_rules": sum(len(rules) for rules in self.rules.values()),
        }
