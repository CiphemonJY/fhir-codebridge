#!/usr/bin/env python3
"""
fhir-codebridge RAG Lookup Layer
=========================
The simplest thing that works: 
  1. Exact code lookup → 100% accuracy, instant
  2. Display text fuzzy match → find by name
  3. Cross-system mapping lookup → verified crosswalk
  4. UMLS slot → hospital provides MRCONSO.RRF, we parse it

No embeddings needed for lookup. No database. No server. 
Just a dict and some string matching. Ponytail approved.
"""

import json
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = _SCRIPT_DIR.parent.parent / "data" / "terminology_parsed"
UMLS_DIR = _SCRIPT_DIR.parent.parent / "data" / "terminology_raw" / "umls"


class RAGLookup:
    """Terminology lookup engine. Load once, query forever."""
    
    def __init__(self, data_dir=DATA_DIR):
        self.data_dir = Path(data_dir)
        self.by_code = {}        # "SYSTEM|CODE" → {code, system, display}
        self.by_display = {}     # lowercase display → list of entries
        self.crosswalk = {}      # "SOURCE_SYSTEM|SOURCE_CODE" → list of targets
        self.systems = {}        # system → count
        self.umls_loaded = False
        self.umls_api = None
        self._prefix_index = {}  # first-3-chars → list of display strings
        self._load()
        self._init_umls_api()
    
    def _load(self):
        """Load all available terminology data.
        
        Auto-discovers all .json files in data/terminology_parsed/.
        Only ships with verified data from project sources.
        Hospitals add more by dropping UMLS files into data/terminology_raw/umls/.
        """
        # Auto-discover and load all JSON files in the data directory
        # Exception: crosswalk_v3.json is loaded separately as crosswalk data
        for path in sorted(self.data_dir.glob("*.json")):
            if path.name == "crosswalk_v3.json":
                continue
            if path.name == "README.md":
                continue
            try:
                with open(path) as f:
                    entries = json.load(f)
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if 'code' not in entry or 'system' not in entry or 'display' not in entry:
                        continue
                    key = f"{entry['system']}|{entry['code']}"
                    if key in self.by_code:
                        continue  # Dedup
                    self.by_code[key] = entry
                    display_lower = entry['display'].lower()
                    if display_lower not in self.by_display:
                        self.by_display[display_lower] = []
                    self.by_display[display_lower].append(entry)
                    sys_name = entry['system']
                    self.systems[sys_name] = self.systems.get(sys_name, 0) + 1
            except (json.JSONDecodeError, KeyError) as e:
                print(f"Warning: Could not load {path.name}: {e}")
        
        # Load crosswalk mappings
        cw_path = self.data_dir / "crosswalk_v3.json"
        if cw_path.exists():
            with open(cw_path) as f:
                mappings = json.load(f)
            for m in mappings:
                source_key = m['source']
                if source_key not in self.crosswalk:
                    self.crosswalk[source_key] = []
                self.crosswalk[source_key].append({
                    'target_code': m['target_code'],
                    'target_system': m['target_system'],
                    'target_display': m['target_display'],
                    'similarity': m['similarity'],
                    'same_system': m['same_system']
                })
        
        # Build prefix index for fast fuzzy lookup (first 3 chars → display strings)
        for display in self.by_display:
            prefix = display[:3] if len(display) >= 3 else display
            if prefix not in self._prefix_index:
                self._prefix_index[prefix] = []
            self._prefix_index[prefix].append(display)
        
        # Try to load UMLS if hospital provided it
        self._try_load_umls()
    
    def _init_umls_api(self):
        """If LISA_UMLS_API_KEY is set, enable UMLS UTS API for live lookups."""
        # Read from env or Docker secret file
        key = os.environ.get("LISA_UMLS_API_KEY")
        if not key:
            file_path = os.environ.get("LISA_UMLS_API_KEY_FILE")
            if file_path and os.path.exists(file_path):
                with open(file_path) as f:
                    key = f.read().strip()
        if key:
            try:
                from rag.umls_api import UMLSClient
                self.umls_api = UMLSClient(api_key=key)
                self.umls_loaded = True
                print("UMLS API enabled.")
            except Exception as e:
                print(f"UMLS API init failed: {e}")
    
    def _try_load_umls(self):
        """If hospital dropped MRCONSO.RRF into data/terminology_raw/umls/, load it."""
        mrconso = UMLS_DIR / "MRCONSO.RRF"
        if not mrconso.exists():
            return
        
        count = 0
        with open(mrconso, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                parts = line.strip().split('|')
                if len(parts) < 15:
                    continue
                # MRCONSO: CUI|LAT|TS|LUI|STT|SUI|ISPREF|AUI|SAUI|SCUI|SDUI|SAB|TTY|CODE|STR|...
                lat = parts[1].strip()
                sab = parts[11].strip()   # source abbreviation
                tty = parts[12].strip()   # term type
                code = parts[13].strip()  # code in source system
                name = parts[14].strip()  # string
                suppress = parts[16].strip() if len(parts) > 16 else ''
                is_pref = parts[6].strip() if len(parts) > 6 else ''
                
                # Only English, preferred terms, non-suppressed
                if lat != 'ENG' or suppress == 'O' or is_pref != 'Y':
                    continue
                
                # Map UMLS source abbreviations to our system names
                sys_map = {
                    'ICD10CM': 'ICD-10-CM',
                    'SNOMEDCT_US': 'SNOMED-CT',
                    'LNC': 'LOINC',
                    'RXNORM': 'RXNORM',
                    'CDT': 'CDT',
                    'CPT': 'CPT',
                }
                sys_name = sys_map.get(sab, sab)
                
                key = f"{sys_name}|{code}"
                if key not in self.by_code:
                    entry = {'code': code, 'system': sys_name, 'display': name}
                    self.by_code[key] = entry
                    display_lower = name.lower()
                    if display_lower not in self.by_display:
                        self.by_display[display_lower] = []
                    self.by_display[display_lower].append(entry)
                    self.systems[sys_name] = self.systems.get(sys_name, 0) + 1
                    count += 1
        
        if count > 0:
            self.umls_loaded = True
            print(f"UMLS loaded: +{count} terms from MRCONSO.RRF")
    
    def _normalize_code(self, system, code):
        """Normalize ICD-10-CM codes to handle dot/no-dot variants."""
        code = code.strip()
        if system == 'ICD-10-CM' and '.' not in code and len(code) > 3:
            # E119 → E11.9 (insert dot after 3rd char)
            code = code[:3] + '.' + code[3:]
        return code
    
    def lookup_code(self, system, code):
        """Exact code lookup. Returns entry or None."""
        # Try all code variants: dotted, no-dot, normalized
        variants = [code, code.replace('.', '')]
        normalized = self._normalize_code(system, code)
        if normalized != code:
            variants.append(normalized)
        for v in variants:
            result = self.by_code.get(f"{system}|{v}")
            if result:
                return result
        # Try all systems if not found with specified system (bare code fallback)
        for v in variants:
            for sys_name in self.systems:
                if sys_name == system:
                    continue
                result = self.by_code.get(f"{sys_name}|{v}")
                if result:
                    return result
        return None
    
    def lookup_fhir_uri(self, uri):
        """Look up a code by FHIR canonical URI (e.g., 'http://snomed.info/sct|128613002')."""
        if '|' not in uri:
            # Bare code — try all systems
            return self.lookup_code('', uri)
        sys_uri, code = uri.split('|', 1)
        system = self.URI_TO_SYSTEM.get(sys_uri, '')
        if system:
            return self.lookup_code(system, code)
        # Unknown URI — try as bare code
        return self.lookup_code('', code)
    
    # Common medical abbreviations → full terms for fuzzy lookup
    ABBREVIATIONS = {
        'htn': 'essential hypertension',
        'hld': 'hyperlipidemia',
        't2dm': 'type 2 diabetes mellitus without complications',
        't1dm': 'type 1 diabetes mellitus without complications',
        'dm2': 'type 2 diabetes mellitus without complications',
        'dm1': 'type 1 diabetes mellitus without complications',
        'chf': 'heart failure',
        'cad': 'coronary artery disease',
        'copd': 'chronic obstructive pulmonary disease',
        'ckd': 'chronic kidney disease',
        'esrd': 'end stage renal disease',
        'afib': 'atrial fibrillation',
        'uti': 'urinary tract infection',
        'uri': 'upper respiratory infection',
        'sob': 'shortness of breath',
        'cp': 'chest pain',
        'abd': 'abdominal',
        'nvd': 'nausea vomiting diarrhea',
        'dvt': 'deep vein thrombosis',
        'pe': 'pulmonary embolism',
        'mi': 'myocardial infarction',
        'cva': 'cerebrovascular accident',
        'tia': 'transient ischemic attack',
        'gerd': 'gastroesophageal reflux disease',
        'ibd': 'inflammatory bowel disease',
        'ibs': 'irritable bowel syndrome',
        'pud': 'peptic ulcer disease',
        'pna': 'pneumonia',
        'cap': 'pneumonia',
        'hap': 'pneumonia',
        'aki': 'acute kidney injury',
        'bph': 'benign prostatic hyperplasia',
        'ra': 'rheumatoid arthritis',
        'oa': 'osteoarthritis',
        'sle': 'systemic lupus erythematosus',
        'ms': 'multiple sclerosis',
        'als': 'amyotrophic lateral sclerosis',
        'mrsa': 'methicillin resistant staphylococcus aureus',
        'mdd': 'major depressive disorder',
        'gad': 'generalized anxiety disorder',
        'sepsis': 'sepsis',
        'septic shock': 'septic shock',
        'stroke': 'cerebral infarction',
        'pneumonia': 'pneumonia',
        'anxiety': 'anxiety disorder',
        'migraine': 'migraine',
        'back pain': 'low back pain',
        'lumbago': 'low back pain',
        'acute renal failure': 'acute kidney failure',
        'septicemia': 'septicemia',
        'hyperkalemia': 'hyperkalemia',
        'hyponatremia': 'hyponatremia',
        'anemia': 'anemia',
        'cellulitis': 'cellulitis',
        'appendicitis': 'appendicitis',
        'cholecystitis': 'cholecystitis',
        'pancreatitis': 'pancreatitis',
        'hepatitis': 'hepatitis',
        'cirrhosis': 'cirrhosis',
        'osteoporosis': 'osteoporosis',
        'hypothyroidism': 'hypothyroidism',
        'hyperthyroidism': 'hyperthyroidism',
        'high blood pressure': 'essential hypertension',
        'diabetes type 2': 'type 2 diabetes mellitus',
        'type 2 diabetes': 'type 2 diabetes mellitus',
        'atrial fibrillation': 'atrial fibrillation',
        'congestive heart failure': 'heart failure',
    }
    
    # Direct synonym-to-code mappings for common clinical terms
    # (bypasses fuzzy matching for high-confidence lookups)
    SYNONYM_TO_CODE = {
        'type 2 diabetes': ('ICD-10-CM', 'E11.9'),
        'type 2 diabetes mellitus': ('ICD-10-CM', 'E11.9'),
        't2dm': ('ICD-10-CM', 'E11.9'),
        'diabetes type 2': ('ICD-10-CM', 'E11.9'),
        'hypertension': ('ICD-10-CM', 'I10'),
        'htn': ('ICD-10-CM', 'I10'),
        'high blood pressure': ('ICD-10-CM', 'I10'),
        'essential hypertension': ('ICD-10-CM', 'I10'),
        'chf': ('ICD-10-CM', 'I50.9'),
        'congestive heart failure': ('ICD-10-CM', 'I50.9'),
        'heart failure': ('ICD-10-CM', 'I50.9'),
        'afib': ('ICD-10-CM', 'I48.91'),
        'atrial fibrillation': ('ICD-10-CM', 'I48.91'),
        'copd': ('ICD-10-CM', 'J44.9'),
        'chronic obstructive pulmonary disease': ('ICD-10-CM', 'J44.9'),
        'stroke': ('ICD-10-CM', 'I63.9'),
        'cerebrovascular accident': ('ICD-10-CM', 'I63.9'),
        'pneumonia': ('ICD-10-CM', 'J18.9'),
        'cap': ('ICD-10-CM', 'J18.9'),
        'ckd': ('ICD-10-CM', 'N18.9'),
        'chronic kidney disease': ('ICD-10-CM', 'N18.9'),
        'sepsis': ('ICD-10-CM', 'A41.9'),
        'septicemia': ('ICD-10-CM', 'A41.9'),
        'mrsa': ('ICD-10-CM', 'A41.02'),
        'mdd': ('ICD-10-CM', 'F32.A'),
        'major depressive disorder': ('ICD-10-CM', 'F32.A'),
        'gad': ('ICD-10-CM', 'F41.1'),
        'generalized anxiety disorder': ('ICD-10-CM', 'F41.1'),
        'anxiety': ('ICD-10-CM', 'F41.1'),
        'migraine': ('ICD-10-CM', 'G43.909'),
        'back pain': ('ICD-10-CM', 'M54.50'),
        'low back pain': ('ICD-10-CM', 'M54.50'),
        'lumbago': ('ICD-10-CM', 'M54.50'),
        'acute renal failure': ('ICD-10-CM', 'N17.9'),
        'acute kidney injury': ('ICD-10-CM', 'N17.9'),
        'aki': ('ICD-10-CM', 'N17.9'),
        'heart attack': ('ICD-10-CM', 'I21.9'),
        'myocardial infarction': ('ICD-10-CM', 'I21.9'),
        'chest pain': ('ICD-10-CM', 'R07.9'),
        'fever': ('ICD-10-CM', 'R50.9'),
        'weakness': ('ICD-10-CM', 'R53.1'),
        'dizziness': ('ICD-10-CM', 'R42'),
    }

    def lookup_display(self, text, system=None, limit=5, threshold=0.6):
        """
        Fuzzy match by display text. Returns list of matches sorted by similarity.
        Uses difflib.SequenceMatcher — no embeddings needed.
        Uses prefix index for performance (avoids scanning all 157K terms).
        """
        text_lower = text.lower().strip()
        
        # Try direct synonym mapping first (highest confidence)
        if text_lower in self.SYNONYM_TO_CODE:
            syn_sys, syn_code = self.SYNONYM_TO_CODE[text_lower]
            if system and syn_sys != system:
                pass  # System mismatch, skip
            else:
                # Try dotted, no-dot, and normalized versions
                for code_variant in [syn_code, syn_code.replace('.', ''), self._normalize_code(syn_sys, syn_code)]:
                    entry = self.by_code.get(f"{syn_sys}|{code_variant}")
                    if entry:
                        return [(1.0, entry)]
        
        # Try abbreviation expansion
        if text_lower in self.ABBREVIATIONS:
            expanded = self.ABBREVIATIONS[text_lower]
            # Exact match on expanded term
            if expanded in self.by_display:
                results = self.by_display[expanded]
                if system:
                    results = [r for r in results if r['system'] == system]
                if results:
                    return [(1.0, r) for r in results[:limit]]
            # Fuzzy match on expanded term
            text_lower = expanded
        
        # Try exact match first
        if text_lower in self.by_display:
            results = self.by_display[text_lower]
            if system:
                results = [r for r in results if r['system'] == system]
            if results:
                return [(1.0, r) for r in results[:limit]]
        
        # Prefix-indexed fuzzy match — only scan terms sharing first 3 chars
        prefix = text_lower[:3] if len(text_lower) >= 3 else text_lower
        candidates = self._prefix_index.get(prefix, [])
        
        # Also add candidates from substring matching (for abbreviation-expanded terms)
        if len(candidates) < 50:
            # Substring match: find displays containing the query text
            for display in self.by_display:
                if text_lower in display or display in text_lower:
                    if display not in candidates:
                        candidates.append(display)
        
        if not candidates:
            # Fallback: scan a sample of all displays
            all_displays = list(self.by_display.keys())
            candidates = all_displays[:5000]  # Sample first 5K for performance
        
        matches = []
        for display in candidates:
            entries = self.by_display.get(display, [])
            # Base ratio from SequenceMatcher
            ratio = SequenceMatcher(None, text_lower, display).ratio()
            # Boost: if query is contained in display, boost ratio
            if text_lower in display:
                ratio = max(ratio, 0.85)
            # Boost: if display is contained in query, boost ratio
            if display in text_lower:
                ratio = max(ratio, 0.80)
            # Penalty: long displays with extra specificity (e.g., 'with hyperglycemia')
            if len(display) > len(text_lower) * 1.5:
                ratio *= 0.9
            if ratio >= threshold:
                for entry in entries:
                    if system and entry['system'] != system:
                        continue
                    matches.append((ratio, entry))
        
        matches.sort(key=lambda x: -x[0])
        return matches[:limit]
    
    # Map short system names to FHIR canonical URIs
    SYSTEM_TO_URI = {
        'ICD-10-CM': 'http://hl7.org/fhir/sid/icd-10-cm',
        'ICD-10': 'http://hl7.org/fhir/sid/icd-10',
        'SNOMED-CT': 'http://snomed.info/sct',
        'SNOMED': 'http://snomed.info/sct',
        'LOINC': 'http://loinc.org',
        'RXNORM': 'http://www.nlm.nih.gov/research/umls/rxnorm',
        'RxNorm': 'http://www.nlm.nih.gov/research/umls/rxnorm',
        'CDT': 'http://www.ada.org/cdt',
        'CVX': 'http://hl7.org/fhir/sid/cvx',
        'CPT': 'http://www.ama-assn.org/go/cpt',
    }
    # Reverse map: URI → system name (for FHIR URI parsing)
    URI_TO_SYSTEM = {
        'http://hl7.org/fhir/sid/icd-10-cm': 'ICD-10-CM',
        'http://hl7.org/fhir/sid/icd-10': 'ICD-10-CM',
        'http://snomed.info/sct': 'SNOMED-CT',
        'http://loinc.org': 'LOINC',
        'http://www.nlm.nih.gov/research/umls/rxnorm': 'RXNORM',
        'http://www.ada.org/cdt': 'CDT',
        'http://hl7.org/fhir/sid/cvx': 'CVX',
        'http://www.ama-assn.org/go/cpt': 'CPT',
    }
    
    def crosswalk_lookup(self, source_system, source_code):
        """
        Look up verified cross-system mappings.
        Returns list of target mappings with similarity scores.
        """
        # Build candidate keys in all formats the crosswalk might use
        candidates = []
        
        # 1. Direct system|code format
        candidates.append(f"{source_system}|{source_code}")
        
        # 2. FHIR URI|code format (most common in crosswalk data)
        uri = self.SYSTEM_TO_URI.get(source_system)
        if uri:
            candidates.append(f"{uri}|{source_code}")
        
        # 3. If source_system is already a URI, try it directly
        if source_system.startswith('http') or source_system.startswith('urn'):
            candidates.append(f"{source_system}|{source_code}")
        
        # 4. Bare code (some crosswalk entries might use this)
        candidates.append(source_code)
        
        # 5. Try all known URIs with this code (brute force for URI-named systems)
        for sys_uri in self.SYSTEM_TO_URI.values():
            candidates.append(f"{sys_uri}|{source_code}")
        
        # 6. Normalized ICD-10 code (dot/no-dot variants)
        if source_system in ('ICD-10-CM', 'ICD-10'):
            norm = self._normalize_code(source_system, source_code)
            if norm != source_code:
                candidates.append(f"http://hl7.org/fhir/sid/icd-10|{norm}")
                candidates.append(f"http://hl7.org/fhir/sid/icd-10-cm|{norm}")
                candidates.append(norm)
            # Also try without dot if source has dot
            no_dot = source_code.replace('.', '')
            if no_dot != source_code:
                candidates.append(f"http://hl7.org/fhir/sid/icd-10|{no_dot}")
                candidates.append(f"http://hl7.org/fhir/sid/icd-10-cm|{no_dot}")
        
        # Deduplicate while preserving order
        seen = set()
        unique_candidates = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                unique_candidates.append(c)
        
        for key in unique_candidates:
            if key in self.crosswalk:
                return self.crosswalk[key]
        return []
    
    def map_term(self, code=None, system=None, display=None, target_system=None, threshold=0.6):
        """
        Full mapping pipeline:
        1. Exact code lookup (100% confidence)
        2. Crosswalk lookup (verified mapping)
        3. Fuzzy display match (neural model territory for unknowns)
        
        Returns: {found, source, targets, confidence, method}
        """
        result = {
            'found': False,
            'source': None,
            'targets': [],
            'confidence': 0.0,
            'method': None
        }
        
        # Step 1: Exact lookup
        if code and system:
            entry = self.lookup_code(system, code)
            if entry:
                result['source'] = entry
                result['found'] = True
                result['confidence'] = 1.0
                result['method'] = 'exact_code_lookup'
        
        # Step 2: Crosswalk
        if code and system:
            cw_results = self.crosswalk_lookup(system, code)
            if cw_results:
                if target_system:
                    cw_results = [r for r in cw_results if r['target_system'] == target_system]
                for r in cw_results:
                    result['targets'].append({
                        'code': r['target_code'],
                        'system': r['target_system'],
                        'display': r['target_display'],
                        'confidence': r['similarity'],
                        'method': 'verified_crosswalk'
                    })
        
        # Step 3: Fuzzy display match (fallback for unknowns)
        if display and not result['found']:
            matches = self.lookup_display(display, system=system, threshold=threshold)
            if matches:
                result['found'] = True
                result['source'] = matches[0][1]
                result['confidence'] = matches[0][0]
                result['method'] = 'fuzzy_display_match'
        
        # Step 4: If we found source but no crosswalk targets, try display match in target system
        if result['source'] and target_system and not result['targets']:
            src_display = result['source']['display']
            matches = self.lookup_display(src_display, system=target_system, threshold=threshold)
            for score, entry in matches:
                result['targets'].append({
                    'code': entry['code'],
                    'system': entry['system'],
                    'display': entry['display'],
                    'confidence': score,
                    'method': 'fuzzy_cross_match'
                })
        
        # Step 5: UMLS API fallback — if local data didn't find cross-system mappings
        if self.umls_api and code and system and not result['targets'] and target_system:
            try:
                umls_mappings = self.umls_api.get_code_mappings(system, code)
                for m in umls_mappings:
                    if m['system'] == target_system or (not target_system):
                        result['targets'].append(m)
                        # If we didn't find the source locally, use UMLS for that too
                        if not result['found'] and m['system'] == system:
                            result['found'] = True
                            result['source'] = {'code': m['code'], 'system': m['system'], 'display': m['display']}
                            result['confidence'] = 1.0
                            result['method'] = 'umls_api_lookup'
            except Exception:
                pass  # UMLS API is best-effort, local data takes priority
        
        return result
    
    def stats(self):
        """Return loaded terminology statistics."""
        return {
            'total_terms': len(self.by_code),
            'by_system': dict(self.systems),
            'crosswalk_mappings': sum(len(v) for v in self.crosswalk.values()),
            'umls_loaded': self.umls_loaded,
            'data_sources': {
                'shipped': 'CDT (397), LOINC core (23), RxNorm (500), db_523 ontology (523), crosswalk (1,898)',
                'hospital_provided': 'UMLS MRCONSO.RRF — adds 600K+ terms when loaded',
            },
            'gaps': {
                'SNOMED-CT': 'Requires UMLS license — hospital provides MRCONSO.RRF or SNOMED US Edition',
                'ICD-10-CM': 'Available via UMLS or CMS download — hospital provides file',
                'LOINC': 'Requires free registration at loinc.org — hospital provides download',
                'RxNorm': 'Partial (500 shipped). Full set (~81K) via UMLS or NLM RxNorm download',
            }
        }
    
    def load_umls_from_file(self, mrconso_path):
        """Load UMLS from a hospital-provided MRCONSO.RRF file."""
        global UMLS_DIR
        # Copy or symlink the file into our expected location
        umls_dir = UMLS_DIR
        umls_dir.mkdir(parents=True, exist_ok=True)
        
        # Just read from the provided path directly
        count = 0
        with open(mrconso_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                parts = line.strip().split('|')
                if len(parts) < 15:
                    continue
                lat = parts[1].strip()
                sab = parts[11].strip()
                code = parts[13].strip()
                name = parts[14].strip()
                suppress = parts[16].strip() if len(parts) > 16 else ''
                is_pref = parts[6].strip() if len(parts) > 6 else ''
                
                if lat != 'ENG' or suppress == 'O' or is_pref != 'Y':
                    continue
                
                sys_map = {
                    'ICD10CM': 'ICD-10-CM',
                    'SNOMEDCT_US': 'SNOMED-CT',
                    'LNC': 'LOINC',
                    'RXNORM': 'RXNORM',
                    'CDT': 'CDT',
                    'CPT': 'CPT',
                }
                sys_name = sys_map.get(sab, sab)
                key = f"{sys_name}|{code}"
                
                if key not in self.by_code:
                    entry = {'code': code, 'system': sys_name, 'display': name}
                    self.by_code[key] = entry
                    display_lower = name.lower()
                    if display_lower not in self.by_display:
                        self.by_display[display_lower] = []
                    self.by_display[display_lower].append(entry)
                    self.systems[sys_name] = self.systems.get(sys_name, 0) + 1
                    count += 1
        
        self.umls_loaded = True
        return count


    def map_with_confidence(self, code=None, system=None, display=None, target_system=None):
        """
        Full mapping pipeline with confidence-based routing.
        Returns: result + action (auto_accept | review | reject)
        
        Thresholds (from LLM Council recommendation):
          ≥ 0.95 → auto_accept (verified lookup or exact match)
          0.70-0.95 → review (coder confirms before billing)
          < 0.70 → reject (human must code from scratch)
        """
        result = self.map_term(
            code=code, system=system, display=display,
            target_system=target_system, threshold=0.5
        )
        
        # If code-based lookup failed, try as display text
        if not result['found'] and code and not display:
            # The 'code' might actually be a display term (e.g., 'type 2 diabetes')
            result = self.map_term(
                code=None, system=system, display=code,
                target_system=target_system, threshold=0.5
            )
        
        # Determine action based on best confidence
        best_conf = result['confidence']
        best_target_conf = max([t['confidence'] for t in result['targets']], default=0)
        effective_conf = max(best_conf, best_target_conf)
        
        if effective_conf >= 0.95:
            action = 'auto_accept'
        elif effective_conf >= 0.70:
            action = 'review'
        else:
            action = 'reject'
        
        result['action'] = action
        result['effective_confidence'] = effective_conf
        result['requires_human_review'] = action != 'auto_accept'
        
        return result


# CLI for testing
if __name__ == '__main__':
    import sys
    
    rag = RAGLookup()
    stats = rag.stats()
    
    print("=== fhir-codebridge RAG Lookup Engine ===\n")
    print(f"Total terms loaded: {stats['total_terms']:,}")
    print(f"Crosswalk mappings: {stats['crosswalk_mappings']:,}")
    print(f"UMLS loaded: {stats['umls_loaded']}")
    print("\nBy system:")
    for sys_name, count in sorted(stats['by_system'].items(), key=lambda x: -x[1]):
        print(f"  {sys_name:<15} {count:>7,}")
    
    print(f"\nGaps (hospital provides):")
    for sys_name, note in stats['gaps'].items():
        print(f"  {sys_name}: {note}")
    
    # Demo queries
    print("\n" + "=" * 60)
    print("=== DEMO QUERIES ===\n")
    
    demos = [
        # (code, system, display, target_system, description)
        ("E11.9", "ICD-10-CM", None, "SNOMED-CT", "Type 2 diabetes → SNOMED-CT"),
        ("D0120", "CDT", None, "ICD-10-CM", "Dental cleaning → ICD-10-CM"),
        (None, None, "metformin", "RXNORM", "Metformin by name → RxNorm"),
        (None, None, "chest x-ray", "LOINC", "Chest X-ray by name → LOINC"),
        ("44054006", "SNOMED-CT", None, "ICD-10-CM", "Type 2 diabetes SNOMED → ICD-10-CM"),
        ("A000", "ICD-10-CM", None, None, "Cholera code lookup"),
    ]
    
    for code, system, display, target, desc in demos:
        result = rag.map_with_confidence(code=code, system=system, display=display, target_system=target)
        print(f"Query: {desc}")
        print(f"  Input: {system or 'text'}|{code or display}")
        print(f"  Action: {result['action'].upper()} (confidence: {result['effective_confidence']:.1%})")
        if result['found']:
            print(f"  Source: {result['source']['system']}|{result['source']['code']} — {result['source']['display']}")
            print(f"  Match: {result['confidence']:.1%} via {result['method']}")
        else:
            print(f"  Source: NOT FOUND")
        if result['targets']:
            for t in result['targets'][:3]:
                print(f"  → {t['system']}|{t['code']} — {t['display']} ({t['confidence']:.1%}, {t['method']})")
        else:
            print(f"  → No cross-system mappings found")
        print()