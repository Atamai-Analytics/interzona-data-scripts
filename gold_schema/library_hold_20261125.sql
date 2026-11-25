-- Library licence hold, step 1 (25 Nov 2026, interzona_cm): full text of 13 documents that were never licensed for redistribution.
-- 81 marked "Confidential - Client Deliverable"; 36, 37 S&P Global draft market reports; 77 S&P Global price outlook; 66 commercial
-- newsletter (NM Advisory); 132 Deutsche Bank Research; 83 consulting practice report; 90, 102, 131 investment research; 110 Silverado
-- Rare Earth Trade Report (all rights reserved); 55 SDSG REE inventory (all rights reserved); 406 UNCTAD Trade and Development Report
-- 2026 (all rights reserved). Their chunks (text + embeddings) move to licence_hold (app role cannot read it); the document rows stay
-- (other tables reference them) but are set is_active = false. Facts already extracted from them (e.g. SDSG occurrence facts) stay.

-- ================================ APPLY ================================
BEGIN;
CREATE TABLE licence_hold.doc_chunks_20261125 AS
  SELECT * FROM docs.document_chunks WHERE document_id IN (36,37,55,66,77,81,83,90,102,110,131,132,406);
DELETE FROM docs.document_chunks WHERE document_id IN (36,37,55,66,77,81,83,90,102,110,131,132,406);
UPDATE docs.documents SET is_active = false WHERE document_id IN (36,37,55,66,77,81,83,90,102,110,131,132,406);
REVOKE ALL ON ALL TABLES IN SCHEMA licence_hold FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA licence_hold FROM cm_app_readonly;
COMMIT;

-- ================================ ROLLBACK (per document, only with the rights holder's permission) ================================
-- BEGIN;
-- INSERT INTO docs.document_chunks SELECT * FROM licence_hold.doc_chunks_20261125 WHERE document_id IN (<ids>);
-- UPDATE docs.documents SET is_active = true WHERE document_id IN (<ids>);
-- DELETE FROM licence_hold.doc_chunks_20261125 WHERE document_id IN (<ids>);
-- COMMIT;
