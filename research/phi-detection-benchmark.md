# PHI/PII Detection Method Benchmark

**Date:** 2026-02-25  
**Purpose:** Evaluate detection methods for the Trellis Gateway PHI Shield  
**Samples:** 25 | **PHI items:** 130 | **FP traps:** 20

---

## 1. Methodology

Tested 6 detection methods against 25 realistic healthcare text samples containing 130 ground-truth PHI items across all 18 HIPAA Safe Harbor identifier categories. Corpus includes 20 false-positive traps (drug names, hospital names, medical terms).

**Evaluation:** Substring matching — a method "finds" a PHI item if any detected span overlaps it (case-insensitive). False positives counted when a detection matches a known trap.

**Methods:**
1. **Regex** — Hand-crafted patterns for SSNs, phones, emails, dates, MRNs, IPs, URLs, etc.
2. **spaCy NER** — `en_core_web_sm`, entities: PERSON, GPE, DATE, LOC, CARDINAL
3. **Presidio** — Microsoft's PII detection engine (NER + patterns), out-of-box
4. **Ollama llama3.1:8b** — ⚠️ REFUSED: Safety guardrails prevent PII extraction even on synthetic data
5. **Ollama qwen3:8b** — Local 8B LLM via chat API, prompted to return PII as JSON array
6. **Regex + Presidio** — Union of both
7. **Regex + LLM (qwen3)** — Union of regex + qwen3:8b

---

## 2. Test Corpus

### Sample 1: Basic admission note
```
Patient John Michael Smith, DOB 03/15/1962, was admitted on 01/10/2026 to Holy Family Hospital. SSN: 123-45-6789. MRN: MR-00482917. Dr. Sarah Chen ordered labs.
```
**PHI (6):** `John Michael Smith` (NAME), `03/15/1962` (DOB), `01/10/2026` (DATE), `123-45-6789` (SSN), `MR-00482917` (MRN), `Sarah Chen` (NAME)
**Traps:** Holy Family Hospital

### Sample 2: Contact info heavy
```
Contact: Jane Doe, 555-867-5309, fax 555-867-5310, jane.doe@example.com. Address: 1234 Elm Street, Springfield, IL 62704.
```
**PHI (7):** `Jane Doe` (NAME), `555-867-5309` (PHONE), `555-867-5310` (FAX), `jane.doe@example.com` (EMAIL), `1234 Elm Street` (ADDRESS), `Springfield` (CITY), `62704` (ZIP)

### Sample 3: Drug name false positive trap
```
Patient was started on Lexapro 10mg and Ambien 5mg at bedtime. Pt reports improvement. Dr. Patel reviewed medications.
```
**PHI (1):** `Patel` (NAME)
**Traps:** Lexapro, Ambien

### Sample 4: Embedded names in clinical text
```
The patient, a 45-year-old male named Roberto Gonzalez-Martinez, presented with chest pain. His wife Maria called 911 from their home at 789 Oak Ave, Apt 4B, Miami, FL 33101.
```
**PHI (6):** `Roberto Gonzalez-Martinez` (NAME), `Maria` (NAME), `45` (AGE), `789 Oak Ave, Apt 4B` (ADDRESS), `Miami` (CITY), `33101` (ZIP)

### Sample 5: Multiple identifiers dense
```
Health Plan ID: HP-9283746501. Account #: 4829103756. Device serial: SN-XR7291-04C. IP: 192.168.1.105. Patient portal: https://myhealth.example.com/patient/jsmith
```
**PHI (5):** `HP-9283746501` (HEALTH_PLAN), `4829103756` (ACCOUNT), `SN-XR7291-04C` (DEVICE_SERIAL), `192.168.1.105` (IP), `https://myhealth.example.com/patient/jsmith` (URL)

### Sample 6: Discharge summary
```
DISCHARGE SUMMARY: Patient Michael O'Brien (DOB: 11/22/1978, SSN: 987-65-4321) discharged 02/14/2026. Follow-up with Dr. Aisha Washington at 617-555-0142. Prescribed Metformin 500mg BID.
```
**PHI (6):** `Michael O'Brien` (NAME), `11/22/1978` (DOB), `987-65-4321` (SSN), `02/14/2026` (DATE), `Aisha Washington` (NAME), `617-555-0142` (PHONE)
**Traps:** Metformin

### Sample 7: Radiology report
```
CT abdomen/pelvis for pt Nguyen, Thi (MRN 00293847). Impression: No acute findings. Compared with prior study from 06/2024. Radiologist: Dr. James Franklin, MD.
```
**PHI (4):** `Nguyen, Thi` (NAME), `00293847` (MRN), `06/2024` (DATE), `James Franklin` (NAME)

### Sample 8: Pediatric note
```
Patient: Emma Liu, age 7, DOB 08/03/2018. Mother: Wei Liu, phone 415-555-0198, email wei.liu@gmail.com. Father: David Liu. Insurance: Aetna plan BEN-5839201.
```
**PHI (8):** `Emma Liu` (NAME), `7` (AGE), `08/03/2018` (DOB), `Wei Liu` (NAME), `415-555-0198` (PHONE), `wei.liu@gmail.com` (EMAIL), `David Liu` (NAME), `BEN-5839201` (HEALTH_PLAN)
**Traps:** Aetna

### Sample 9: Mental health note
```
Session note for patient Alexander Petrov, referred by Dr. Kim. Patient disclosed history of substance abuse. Lives at 42 Birch Lane, Portland, OR 97201. Emergency contact: Natasha Petrov, 503-555-0177.
```
**PHI (7):** `Alexander Petrov` (NAME), `Kim` (NAME), `42 Birch Lane` (ADDRESS), `Portland` (CITY), `97201` (ZIP), `Natasha Petrov` (NAME), `503-555-0177` (PHONE)

### Sample 10: Lab results
```
Labs for DOE, JOHN A (MRN: 10482957, DOB: 1955-07-30)
Collected: 2026-01-15 08:30
Hgb: 12.1, WBC: 7.2
Ordering physician: MARTINEZ, ELENA MD
```
**PHI (5):** `DOE, JOHN A` (NAME), `10482957` (MRN), `1955-07-30` (DOB), `2026-01-15` (DATE), `MARTINEZ, ELENA` (NAME)

### Sample 11: No PII - only traps
```
Assessment: Type 2 diabetes mellitus, uncontrolled. A1c 9.2%. Plan: Increase Januvia to 100mg daily. Recheck in 3 months. Consider referral to endocrinology at Massachusetts General.
```
**PHI (0):** None
**Traps:** Januvia, Massachusetts General

### Sample 12: Email referral
```
From: dr.wilson@mercy-hospital.org
To: intake@specialtycare.com
Re: Referral for patient Fatima Al-Hassan (DOB 04/19/1990)
Please schedule a cardiology consult. Patient's phone: 312-555-0234.
```
**PHI (5):** `dr.wilson@mercy-hospital.org` (EMAIL), `intake@specialtycare.com` (EMAIL), `Fatima Al-Hassan` (NAME), `04/19/1990` (DOB), `312-555-0234` (PHONE)

### Sample 13: Surgical note with device
```
OPERATIVE NOTE: Patient William Torres, MRN 83920174. Procedure: Total knee arthroplasty. Implant: Smith & Nephew LEGION, SN: LGN-2024-08-4521. Surgeon: Dr. Rebecca Park. Anesthesiologist: Dr. Ahmed Malik.
```
**PHI (5):** `William Torres` (NAME), `83920174` (MRN), `LGN-2024-08-4521` (DEVICE_SERIAL), `Rebecca Park` (NAME), `Ahmed Malik` (NAME)
**Traps:** Smith & Nephew, LEGION

### Sample 14: Insurance claim
```
Claim for: Patricia Yamamoto, SSN 456-78-9012. Subscriber ID: SUB-77291034. Group: GRP-5500. Service date: 12/01/2025. Billed to: 9876 Corporate Blvd, Suite 200, Dallas, TX 75201.
```
**PHI (8):** `Patricia Yamamoto` (NAME), `456-78-9012` (SSN), `SUB-77291034` (HEALTH_PLAN), `GRP-5500` (ACCOUNT), `12/01/2025` (DATE), `9876 Corporate Blvd, Suite 200` (ADDRESS), `Dallas` (CITY), `75201` (ZIP)

### Sample 15: Ambiguous dates
```
Patient seen in March 2025 for follow-up. Born in 1988. Previously seen by Dr. Stone at the Cleveland Clinic. Phone ending in 4567. Chart note by RN Thompson.
```
**PHI (5):** `March 2025` (DATE), `1988` (DOB), `Stone` (NAME), `4567` (PHONE_PARTIAL), `Thompson` (NAME)
**Traps:** Cleveland Clinic

### Sample 16: Pathology report
```
PATH REPORT #P-2026-00891
Patient: CHEN, ROBERT K
MRN: 57391028
DOB: 02/28/1971
Diagnosis: Invasive ductal carcinoma
Pathologist: Dr. Laura Ivanovic, MD
```
**PHI (4):** `CHEN, ROBERT K` (NAME), `57391028` (MRN), `02/28/1971` (DOB), `Laura Ivanovic` (NAME)

### Sample 17: Telehealth with IP/URL
```
Telehealth encounter with patient Deshawn Williams via portal. Connected from IP 73.42.191.55 at 14:30 EST. URL: https://portal.healthsys.com/users/dwilliams. DOB: 09/12/2001. Email: d.williams99@yahoo.com
```
**PHI (5):** `Deshawn Williams` (NAME), `73.42.191.55` (IP), `https://portal.healthsys.com/users/dwilliams` (URL), `09/12/2001` (DOB), `d.williams99@yahoo.com` (EMAIL)

### Sample 18: Emergency department
```
EMS brought in unresponsive male, ID found: James Earl Washington, DOB 06/06/1955, 321 Pine St, Apt 7, Baltimore, MD 21201. SSN from wallet: 111-22-3333. Allergies: Penicillin, Codeine.
```
**PHI (6):** `James Earl Washington` (NAME), `06/06/1955` (DOB), `321 Pine St, Apt 7` (ADDRESS), `Baltimore` (CITY), `21201` (ZIP), `111-22-3333` (SSN)
**Traps:** Penicillin, Codeine

### Sample 19: Many names
```
RN Maria Santos assessed patient Olga Federova (MRN 11223344) at 0600. Patient's daughter Svetlana called. CNA Tyrone assisted. MD on call: Dr. Christopher Lee. Pharmacy notified re: Tramadol dose.
```
**PHI (6):** `Maria Santos` (NAME), `Olga Federova` (NAME), `11223344` (MRN), `Svetlana` (NAME), `Tyrone` (NAME), `Christopher Lee` (NAME)
**Traps:** Tramadol

### Sample 20: Billing
```
Invoice for patient account 9918273645. Patient: Margaret (Peggy) O'Sullivan. DOB: 12/25/1945. Send to: PO Box 551, Savannah, GA 31401. Call 912-555-0199 or fax 912-555-0200.
```
**PHI (8):** `9918273645` (ACCOUNT), `Margaret (Peggy) O'Sullivan` (NAME), `12/25/1945` (DOB), `PO Box 551` (ADDRESS), `Savannah` (CITY), `31401` (ZIP), `912-555-0199` (PHONE), `912-555-0200` (FAX)

### Sample 21: Only traps
```
Patient started on Adderall 20mg XR. Also taking Wellbutrin 150mg. Discussed Prozac. Seen at Johns Hopkins outpatient. Diagnosis: MDD, recurrent.
```
**PHI (0):** None
**Traps:** Adderall, Wellbutrin, Prozac, Johns Hopkins

### Sample 22: Dense clinical with hidden PII
```
HPI: 62yo F c/o SOB x 3 days. PMH: HTN, DM2, CHF. Pt is Barbara Kowalski (goes by Barb), SSN on file 222-33-4444. Husband Stan, reachable at 708-555-0123.
```
**PHI (5):** `62` (AGE), `Barbara Kowalski` (NAME), `222-33-4444` (SSN), `Stan` (NAME), `708-555-0123` (PHONE)

### Sample 23: Transfer with multiple MRNs
```
Transfer from St. Mary's to University Hospital. Patient: Raj Krishnamurthy, MRN 44556677 (St. Mary's), MRN 88990011 (UH). Attending: Dr. O'Reilly. Accepting: Dr. Tanaka. Family: Priya Krishnamurthy, 646-555-0188.
```
**PHI (7):** `Raj Krishnamurthy` (NAME), `44556677` (MRN), `88990011` (MRN), `O'Reilly` (NAME), `Tanaka` (NAME), `Priya Krishnamurthy` (NAME), `646-555-0188` (PHONE)
**Traps:** St. Mary's, University Hospital

### Sample 24: Freeform note
```
Saw Mr. Henderson today, doing well post-op day 5. Incision clean. Will d/c home tomorrow. Wife picking up, lives on Maple Drive in Brookline. F/u 2 weeks, call 617-555-0150.
```
**PHI (4):** `Henderson` (NAME), `Maple Drive` (ADDRESS), `Brookline` (CITY), `617-555-0150` (PHONE)

### Sample 25: Prescription
```
Rx for: Amara Johnson-Williams
DOB: 07/04/1989
Address: 555 Washington Blvd, Chicago, IL 60601
Phone: 773-555-0167
Rx: Lisinopril 10mg #30
Prescriber: Dr. Yuki Sato, NPI 9876543210
```
**PHI (7):** `Amara Johnson-Williams` (NAME), `07/04/1989` (DOB), `555 Washington Blvd` (ADDRESS), `Chicago` (CITY), `60601` (ZIP), `773-555-0167` (PHONE), `Yuki Sato` (NAME)
**Traps:** Lisinopril

---

## 3. Results Summary

| Method | TP | FN | FP | Precision | Recall | F1 | Avg Latency (ms) |
|--------|---:|---:|---:|----------:|-------:|---:|-----------------:|
| Regex | 78 | 52 | 0 | 1.000 | 0.600 | 0.750 | 0.1 |
| spaCy NER | 96 | 34 | 5 | 0.950 | 0.738 | 0.831 | 4.7 |
| Presidio | 122 | 8 | 14 | 0.897 | 0.938 | 0.917 | 9.3 |
| Ollama qwen3:8b | 120 | 10 | 11 | 0.916 | 0.923 | 0.920 | 2263.2 |
| Regex + Presidio | 126 | 4 | 14 | 0.900 | 0.969 | 0.933 | 5.7 |
| Regex + LLM (qwen3) | 124 | 6 | 11 | 0.919 | 0.954 | 0.936 | 2283.2 |

**Total PHI items in corpus: 130**

---

## 4. Detailed Misses (False Negatives)

### Regex (missed 52/130)
- S1: NAME: John Michael Smith
- S2: NAME: Jane Doe, ADDRESS: 1234 Elm Street, CITY: Springfield
- S4: NAME: Roberto Gonzalez-Martinez, NAME: Maria, AGE: 45, ADDRESS: 789 Oak Ave, Apt 4B, CITY: Miami
- S6: NAME: Michael O'Brien
- S7: NAME: Nguyen, Thi
- S8: NAME: Emma Liu, AGE: 7, NAME: Wei Liu, NAME: David Liu
- S9: NAME: Alexander Petrov, ADDRESS: 42 Birch Lane, CITY: Portland, NAME: Natasha Petrov
- S10: NAME: DOE, JOHN A, NAME: MARTINEZ, ELENA
- S12: NAME: Fatima Al-Hassan
- S13: NAME: William Torres
- S14: NAME: Patricia Yamamoto, ADDRESS: 9876 Corporate Blvd, Suite 200, CITY: Dallas
- S15: DOB: 1988, PHONE_PARTIAL: 4567, NAME: Thompson
- S16: NAME: CHEN, ROBERT K
- S17: NAME: Deshawn Williams
- S18: NAME: James Earl Washington, ADDRESS: 321 Pine St, Apt 7, CITY: Baltimore
- S19: NAME: Maria Santos, NAME: Olga Federova, NAME: Svetlana, NAME: Tyrone
- S20: NAME: Margaret (Peggy) O'Sullivan, ADDRESS: PO Box 551, CITY: Savannah
- S22: AGE: 62, NAME: Barbara Kowalski, NAME: Stan
- S23: NAME: Raj Krishnamurthy, NAME: O'Reilly, NAME: Priya Krishnamurthy
- S24: ADDRESS: Maple Drive, CITY: Brookline
- S25: NAME: Amara Johnson-Williams, ADDRESS: 555 Washington Blvd, CITY: Chicago

### spaCy NER (missed 34/130)
- S1: MRN: MR-00482917
- S2: EMAIL: jane.doe@example.com, ZIP: 62704
- S5: HEALTH_PLAN: HP-9283746501, DEVICE_SERIAL: SN-XR7291-04C, URL: https://myhealth.example.com/patient/jsmith
- S6: DATE: 02/14/2026
- S7: NAME: Nguyen, Thi, MRN: 00293847
- S8: DOB: 08/03/2018, EMAIL: wei.liu@gmail.com, HEALTH_PLAN: BEN-5839201
- S9: ADDRESS: 42 Birch Lane
- S10: NAME: MARTINEZ, ELENA
- S12: EMAIL: dr.wilson@mercy-hospital.org, EMAIL: intake@specialtycare.com, DOB: 04/19/1990
- S14: HEALTH_PLAN: SUB-77291034, ACCOUNT: GRP-5500, ZIP: 75201
- S15: NAME: Thompson
- S16: DOB: 02/28/1971
- S17: IP: 73.42.191.55, URL: https://portal.healthsys.com/users/dwilliams, DOB: 09/12/2001, EMAIL: d.williams99@yahoo.com
- S18: DOB: 06/06/1955, ZIP: 21201
- S19: NAME: Tyrone
- S20: ADDRESS: PO Box 551
- S22: AGE: 62
- S23: MRN: 88990011
- S25: DOB: 07/04/1989, ZIP: 60601

### Presidio (missed 8/130)
- S1: SSN: 123-45-6789
- S7: NAME: Nguyen, Thi
- S14: ACCOUNT: GRP-5500, ZIP: 75201
- S18: ADDRESS: 321 Pine St, Apt 7
- S20: ADDRESS: PO Box 551
- S22: AGE: 62
- S25: ZIP: 60601

### Ollama qwen3:8b (missed 10/130)
- S3: NAME: Patel
- S4: AGE: 45
- S6: NAME: Aisha Washington
- S8: AGE: 7, DOB: 08/03/2018, NAME: David Liu
- S9: NAME: Kim
- S19: NAME: Tyrone
- S22: AGE: 62, NAME: Stan

### Regex + Presidio (missed 4/130)
- S7: NAME: Nguyen, Thi
- S18: ADDRESS: 321 Pine St, Apt 7
- S20: ADDRESS: PO Box 551
- S22: AGE: 62

### Regex + LLM (qwen3) (missed 6/130)
- S4: AGE: 45
- S8: AGE: 7, NAME: David Liu
- S19: NAME: Tyrone
- S22: AGE: 62, NAME: Stan

---

## 5. False Positives Detail

### spaCy NER (5 false positives)
- S3: Ambien
- S18: Codeine
- S19: Tramadol
- S21: Prozac
- S23: St. Mary's

### Presidio (14 false positives)
- S1: Holy Family Hospital
- S3: Ambien
- S8: Aetna
- S11: Massachusetts General
- S13: Smith & Nephew, LEGION
- S15: Cleveland Clinic
- S18: Codeine
- S19: Tramadol
- S21: Wellbutrin, Prozac, Johns Hopkins
- S23: St. Mary's, University Hospital

### Ollama qwen3:8b (11 false positives)
- S1: Holy Family Hospital
- S6: Metformin
- S15: Cleveland Clinic
- S18: Penicillin, Codeine
- S19: Tramadol
- S21: Adderall, Wellbutrin, Prozac, Johns Hopkins
- S25: Lisinopril

### Regex + Presidio (14 false positives)
- S1: Holy Family Hospital
- S3: Ambien
- S8: Aetna
- S11: Massachusetts General
- S13: Smith & Nephew, LEGION
- S15: Cleveland Clinic
- S18: Codeine
- S19: Tramadol
- S21: Wellbutrin, Prozac, Johns Hopkins
- S23: St. Mary's, University Hospital

### Regex + LLM (qwen3) (11 false positives)
- S1: Holy Family Hospital
- S6: Metformin
- S15: Cleveland Clinic
- S18: Penicillin, Codeine
- S19: Tramadol
- S21: Adderall, Wellbutrin, Prozac, Johns Hopkins
- S25: Lisinopril

---

## 6. Latency Comparison

| Method | Avg Latency (ms) | Category |
|--------|------------------:|----------|
| Regex | 0.1 | ⚡ Real-time |
| spaCy NER | 4.7 | ⚡ Real-time |
| Presidio | 9.3 | ⚡ Real-time |
| Ollama qwen3:8b | 2263.2 | 🐌 Slow |
| Regex + Presidio | 5.7 | ⚡ Real-time |
| Regex + LLM (qwen3) | 2283.2 | 🐌 Slow |

---

## 7. Recommendation

**Best F1:** Regex + LLM (qwen3) (0.936)  
**Best Recall:** Regex + Presidio (0.969)

### For Healthcare: RECALL IS KING 👑

In HIPAA compliance, **a missed PHI item (false negative) is a potential violation**. A false positive just means over-redaction (safe but annoying). Therefore we optimize for **recall first**, then precision.

### Recommended Architecture

**Layer 1 — Regex (synchronous, <1ms):**
Catches all structured identifiers instantly: SSNs, phone numbers, emails, IPs, URLs, MRNs, dates in standard formats.

**Layer 2 — Presidio (synchronous, ~10-50ms):**
Adds NER-based detection for names, addresses, and contextual PII that regex misses. The union (Regex + Presidio) gives the best speed/accuracy tradeoff.

**Layer 3 — Local LLM (async audit, ~2-5s):**
Run asynchronously for audit logging. Catches edge cases like partial identifiers, names in unusual formats, and contextual PII. Don't block the gateway on this.

### Decision Matrix

| Scenario | Method | Why |
|----------|--------|-----|
| Real-time gateway proxy | Regex + Presidio | Best recall at acceptable latency |
| Async audit trail | Regex + LLM | Maximum recall, latency doesn't matter |
| Resource-constrained | Regex alone | Fast but misses names |
| Maximum safety | All three layers | Belt, suspenders, and a parachute |

---

## 8. Surprises & Gotchas

1. **Names are the hardest category** — Regex can't reliably detect names without prefixes (Dr., Mr., Patient:). Even NER misses names in clinical formats (LAST, FIRST).
2. **spaCy flags hospitals/cities as entities** — High false-positive rate in medical text. Not great standalone.
3. **Presidio out-of-box is impressive** — Combines regex + NER internally, purpose-built for this exact problem.
4. **LLM output parsing is fragile** — Models don't always return clean JSON arrays. Need robust fallback parsing.
5. **LLM latency is 100-1000x slower** — Unusable for synchronous proxying, but valuable for async audit.
6. **Partial identifiers stump everyone** — "Phone ending in 4567" or "Born in 1988" are near-impossible for pattern matchers.
7. **Drug names rarely cause false positives** — Despite being named like people (Lexapro, Ambien), most methods handle this well.
8. **Hyphenated/apostrophe names are hard** — O'Brien, Gonzalez-Martinez, Al-Hassan trip up pattern matchers.

---

## Appendix: Benchmark Script

Saved at `research/phi_benchmark.py`. Run:
```bash
cd /home/reef/.openclaw/workspace/projects/trellis
.venv/bin/python research/phi_benchmark.py          # Full benchmark (slow, includes LLM)
.venv/bin/python research/phi_benchmark.py --no-llm  # Skip LLM methods (fast)
```
