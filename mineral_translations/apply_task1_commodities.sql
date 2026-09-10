-- Task 1 (redo): metal commodity links for the 8 AR deposits the Phase-1 parser dropped.
-- The first attempt joined on depno instead of depositid and inserted nothing.
-- depno -> depositid: 5065->2826 5066->2869 5067->2915 5068->2971 5069->3138 5070->2806
--                     5232->3345 26061->1405
BEGIN;

INSERT INTO deposit_commodities (depositid, commodity_id, commodity_role, createdby)
VALUES
  -- 5065-5070 Coslay / El Bochita / La Aurelia / La Lalita / Lincoln / Yanquetruz: "W - Sb"
  (2826, 236, 'PRIMARY', 'claude_deposit_gap_20260910'), (2826, 279, 'SECONDARY', 'claude_deposit_gap_20260910'),
  (2869, 236, 'PRIMARY', 'claude_deposit_gap_20260910'), (2869, 279, 'SECONDARY', 'claude_deposit_gap_20260910'),
  (2915, 236, 'PRIMARY', 'claude_deposit_gap_20260910'), (2915, 279, 'SECONDARY', 'claude_deposit_gap_20260910'),
  (2971, 236, 'PRIMARY', 'claude_deposit_gap_20260910'), (2971, 279, 'SECONDARY', 'claude_deposit_gap_20260910'),
  (3138, 236, 'PRIMARY', 'claude_deposit_gap_20260910'), (3138, 279, 'SECONDARY', 'claude_deposit_gap_20260910'),
  (2806, 236, 'PRIMARY', 'claude_deposit_gap_20260910'), (2806, 279, 'SECONDARY', 'claude_deposit_gap_20260910'),
  -- 5232 Las Mercedes: "W (Cu-Pb-Zn)"
  (3345, 236, 'PRIMARY', 'claude_deposit_gap_20260910'), (3345, 239, 'SECONDARY', 'claude_deposit_gap_20260910'),
  (3345, 241, 'SECONDARY', 'claude_deposit_gap_20260910'), (3345, 242, 'SECONDARY', 'claude_deposit_gap_20260910'),
  -- 26061 Veta Justiniana: "Pb; Ag; Cu; Zn"
  (1405, 241, 'PRIMARY', 'claude_deposit_gap_20260910'), (1405, 248, 'SECONDARY', 'claude_deposit_gap_20260910'),
  (1405, 239, 'SECONDARY', 'claude_deposit_gap_20260910'), (1405, 242, 'SECONDARY', 'claude_deposit_gap_20260910');

SELECT d.depositid, l.external_id AS depno, l.locationname,
       string_agg(c.commodity_symbol || ':' || dc.commodity_role, ', ' ORDER BY dc.commodity_role DESC, c.commodity_symbol) AS commodities
FROM deposit_commodities dc
JOIN deposits d ON d.depositid = dc.depositid
JOIN locations l ON l.locationid = d.locationid
JOIN commodities c ON c.commodity_id = dc.commodity_id
WHERE dc.createdby = 'claude_deposit_gap_20260910'
GROUP BY 1,2,3 ORDER BY 2::int;

COMMIT;
