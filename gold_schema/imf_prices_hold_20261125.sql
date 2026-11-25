-- IMF Primary Commodity Prices (IMF_PCPS) held back, 25 Nov 2026 (interzona_cm).
-- IMF Copyright and Usage, "Special Terms for Statistical Data": free use and redistribution with attribution, but
-- "For any potential commercial reuse of IMF Data, email copyright@imf.org to request permission." Permission not yet asked.
-- The 15 series, their 8,199 monthly prices and 104 outlook-range rows move to schema licence_hold (app role cannot read).
-- World Bank Pink Sheet series stay live (CC BY 4.0 under the World Bank dataset terms; confirmation email drafted).

-- ================================ APPLY ================================
BEGIN;
CREATE TABLE licence_hold.imf_price_series AS SELECT * FROM markets.price_series WHERE source = 'IMF_PCPS';
CREATE TABLE licence_hold.imf_prices AS SELECT * FROM markets.prices WHERE series_id IN (SELECT series_id FROM licence_hold.imf_price_series);
CREATE TABLE licence_hold.imf_price_outlook AS SELECT * FROM markets.price_outlook WHERE series_id IN (SELECT series_id FROM licence_hold.imf_price_series);
DELETE FROM markets.price_outlook WHERE series_id IN (SELECT series_id FROM licence_hold.imf_price_series);
DELETE FROM markets.prices WHERE series_id IN (SELECT series_id FROM licence_hold.imf_price_series);
DELETE FROM markets.price_series WHERE series_id IN (SELECT series_id FROM licence_hold.imf_price_series);
REVOKE ALL ON ALL TABLES IN SCHEMA licence_hold FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA licence_hold FROM cm_app_readonly;
COMMIT;

-- ================================ ROLLBACK (after IMF grants permission) ================================
-- BEGIN;
-- INSERT INTO markets.price_series SELECT * FROM licence_hold.imf_price_series;
-- INSERT INTO markets.prices SELECT * FROM licence_hold.imf_prices;
-- INSERT INTO markets.price_outlook SELECT * FROM licence_hold.imf_price_outlook;
-- DROP TABLE licence_hold.imf_price_outlook, licence_hold.imf_prices, licence_hold.imf_price_series;
-- COMMIT;
-- then set IMF_PRICES_ENABLED = true in src/lib/flags.ts and deploy.
