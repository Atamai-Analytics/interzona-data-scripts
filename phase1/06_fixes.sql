-- Phase 1 step 06: fix 7 type disagreements (SIGAM ficha wins) + depno 24574 name typo
BEGIN;

UPDATE deposits d SET deposit_type_id = 132, deposit_type_local = left(regexp_replace(f.tipo_deposito, ';.*$', ''), 255), modifiedby='claude_sigam_20260910', modifieddate=now() FROM locations l JOIN sigam_fichas f ON f.depno = l.external_id::int WHERE l.locationid=d.locationid AND l.locationtype='DEPOSIT' AND l.external_id = '1';
UPDATE deposits d SET deposit_type_id = 119, deposit_type_local = left(regexp_replace(f.tipo_deposito, ';.*$', ''), 255), modifiedby='claude_sigam_20260910', modifieddate=now() FROM locations l JOIN sigam_fichas f ON f.depno = l.external_id::int WHERE l.locationid=d.locationid AND l.locationtype='DEPOSIT' AND l.external_id = '34';
UPDATE deposits d SET deposit_type_id = 119, deposit_type_local = left(regexp_replace(f.tipo_deposito, ';.*$', ''), 255), modifiedby='claude_sigam_20260910', modifieddate=now() FROM locations l JOIN sigam_fichas f ON f.depno = l.external_id::int WHERE l.locationid=d.locationid AND l.locationtype='DEPOSIT' AND l.external_id = '36';
UPDATE deposits d SET deposit_type_id = 119, deposit_type_local = left(regexp_replace(f.tipo_deposito, ';.*$', ''), 255), modifiedby='claude_sigam_20260910', modifieddate=now() FROM locations l JOIN sigam_fichas f ON f.depno = l.external_id::int WHERE l.locationid=d.locationid AND l.locationtype='DEPOSIT' AND l.external_id = '45';
UPDATE deposits d SET deposit_type_id = 132, deposit_type_local = left(regexp_replace(f.tipo_deposito, ';.*$', ''), 255), modifiedby='claude_sigam_20260910', modifieddate=now() FROM locations l JOIN sigam_fichas f ON f.depno = l.external_id::int WHERE l.locationid=d.locationid AND l.locationtype='DEPOSIT' AND l.external_id = '2014';
UPDATE deposits d SET deposit_type_id = 85, deposit_type_local = left(regexp_replace(f.tipo_deposito, ';.*$', ''), 255), modifiedby='claude_sigam_20260910', modifieddate=now() FROM locations l JOIN sigam_fichas f ON f.depno = l.external_id::int WHERE l.locationid=d.locationid AND l.locationtype='DEPOSIT' AND l.external_id = '3019';
UPDATE deposits d SET deposit_type_id = 156, deposit_type_local = left(regexp_replace(f.tipo_deposito, ';.*$', ''), 255), modifiedby='claude_sigam_20260910', modifieddate=now() FROM locations l JOIN sigam_fichas f ON f.depno = l.external_id::int WHERE l.locationid=d.locationid AND l.locationtype='DEPOSIT' AND l.external_id = '24538';

UPDATE locations SET locationname = 'Salar de Diablillos', modifiedby='claude_sigam_20260910', modifieddate=now()
WHERE locationtype='DEPOSIT' AND external_id = '24574' AND locationname = 'Salar de Diabillos';
UPDATE sigam_deposits SET nombre_de_yacimiento = replace(nombre_de_yacimiento,'Diabillos','Diablillos')
WHERE deposit_id = 24574;

SELECT d.deposit_type_id, l.locationname FROM deposits d JOIN locations l ON l.locationid=d.locationid
WHERE l.external_id IN ('1','34','36','45','2014','3019','24538','24574') ORDER BY l.external_id;
COMMIT;