-- Library licence hold, step 2 (25 Nov 2026, interzona_cm). Licence audit of the full-text library (three research passes plus the
-- documents' own rights pages): these are all rights reserved, non-commercial, no-derivatives, or carry no licence we could find, so
-- the full text is held back and replaced by own-words summaries (new documents, created_by claude_licence_summaries_20261125).
-- Kept as full text: company filings; public-domain / open-licence government and IGO texts (USGS, GA, IEA CC BY, JRC, OECD, World
-- Bank, EITI, UK OGL, Parliament, EU law, Australian and US government); CC BY journal articles; WRI.
-- Large documents: 12 BGS (NC), 35 Hinrich, 39 OGR (BY-NC-ND), 40 Duke (BY-NC), 43 Econ Geol, 48 Indian Bureau of Mines (no licence),
-- 58 Norway (no licence), 59/60/73/404/100 study groups (permission), 61/67 Payne, 63, 64 CFR, 65 ECB, 78 SGB (no licence), 79 REIA,
-- 80 LynAI, 82 APPG, 84 SIPRI, 85/112 Ifri, 87, 91/408 Columbia CGEP, 92 NBER, 93 CMAG, 98 Elsevier, 101/146 WEF, 103 IISS, 104 IAI,
-- 105 EPRS (NC), 106, 111 ERMA, 113 EU Today, 116, 117 CRU, 118 MAC, 120 USSC, 123, 127, 128 RBC, 130, 135/160 UNCTAD, 136 CSIRO,
-- 137 UN SAB, 142 Atlantic Council, 151 Kearney, 153 OGR (BY-NC-ND), 157 CSIS, 161 Canada (Crown copyright), 409, 410 ACF, 411 GCSP,
-- 412 Kleinman, 34 Khaos.
-- Short documents: 89 RCF, 95 EPRS (NC), 96 Euromines, 97 AK, 107 ISDF, 108 Strategic Edge, 124 Mining Victoria, 126 Beacon, 133 LynAI,
-- 138 MINING.COM, 144 news, 145 (journal, licence unconfirmed), 155 opinion, 156 EKN/IPV, 158 news, 159 African Business, 414 HPE.

BEGIN;
CREATE TABLE licence_hold.doc_chunks_20261125_step2 AS
  SELECT * FROM docs.document_chunks WHERE document_id IN (
    12,34,35,39,40,43,48,58,59,60,61,63,64,65,67,73,78,79,80,82,84,85,87,91,92,93,98,100,101,103,104,105,106,111,112,113,116,117,118,
    120,123,127,128,130,135,136,137,142,146,151,153,157,160,161,404,408,409,410,411,412,
    89,95,96,97,107,108,124,126,133,138,144,145,155,156,158,159,414);
DELETE FROM docs.document_chunks WHERE document_id IN (SELECT DISTINCT document_id FROM licence_hold.doc_chunks_20261125_step2);
UPDATE docs.documents SET is_active = false WHERE document_id IN (SELECT DISTINCT document_id FROM licence_hold.doc_chunks_20261125_step2);
REVOKE ALL ON ALL TABLES IN SCHEMA licence_hold FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA licence_hold FROM cm_app_readonly;
COMMIT;
-- Rollback per document: see library_hold_20261125.sql (same pattern, table licence_hold.doc_chunks_20261125_step2).
