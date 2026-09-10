-- Phase 1 step 02: insert 179 new SIGAM deposits
-- locations + deposits in one CTE, then commodities + mineralogy.
BEGIN;

WITH nl AS (
  INSERT INTO locations (locationcode, locationname, locationtype, latitude, longitude,
                         external_id, datasource, datasource_url, countryid, createdby)
  SELECT 'País', v.name, 'DEPOSIT', v.lat, v.lon, v.depno::text,
         'Argentine Geological and Mining Service SEGEMAR', v.url, 23, 'claude_sigam_20260910'
  FROM (VALUES
    (239, 'La Cordobesa', -30.81277, -64.675, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp239.html'),
    (240, 'La Boreal (Lolita, Sisy)', -31.81666, -64.46666, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp240.html'),
    (243, 'La Argentina-Cruz del Señor', -31.23333, -65.31666, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp243.html'),
    (264, 'La Gallinita de Plata-Paganzo-El Espejo', -30.92388, -65.17027, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp264.html'),
    (268, 'La Eufemia', -30.97722, -65.20694, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp268.html'),
    (270, 'La Aguadita-Tronco del Mogote-Judith-Guissel', -30.92333, -65.18055, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp270.html'),
    (271, 'La Ballena-Cola de la Ballena-San Miguel', -30.98638, -65.19027, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp271.html'),
    (272, 'La Casualidad- London', -30.92916, -65.20277, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp272.html'),
    (273, 'La Escopeta', -30.98861, -65.16027, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp273.html'),
    (287, 'Juan Chiquito', -30.97722, -65.17361, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp287.html'),
    (510, 'Area Cerro Martín', -41.36666, -71.65, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp510.html'),
    (2095, 'La Esperanza, Los Correa, Isla Verde, 12 de octubr', -29.57138, -64.08888, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp2095.html'),
    (2199, 'Aurora', -39.09444, -67.05166, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp2199.html'),
    (4007, 'La Bismutina', -31.15, -65.26666, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp4007.html'),
    (5105, 'La Dita,La Rubia,Valeria,Santa Bárbara', -31.73333, -65.15, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp5105.html'),
    (5126, 'La Cubierta, Quebrada Honda', -31.2, -64.55, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp5126.html'),
    (5136, 'Josefina', -32.86666, -64.9, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp5136.html'),
    (5137, 'La Carmelita', -33.04999, -65.0, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp5137.html'),
    (5138, 'La Cuesta, San Francisco', -30.85, -64.45, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp5138.html'),
    (5233, 'San José', -27.63333, -65.86666, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp5233.html'),
    (11168, 'Bentonita Lago Pellegrini; Bentonita del Lago; Gustavo; Exigentes; Rola; Breyitta', -38.80805, -68.05944, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp11168.html'),
    (11175, 'La Calera; Dumesnil', -31.31527, -64.43333, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp11175.html'),
    (11261, 'Vipos-Tapia', -26.59722, -65.29472, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp11261.html'),
    (11358, 'La Argentina', -31.22194, -65.30277, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp11358.html'),
    (24561, 'Anit (A1-M1)', -39.92527, -66.84555, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp24561.html'),
    (24581, 'Calcatreu; Nelson', -41.90916, -69.55694, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp24581.html'),
    (24582, 'Calcatreu; Castro Sur', -41.84416, -69.5125, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp24582.html'),
    (24588, 'Bajo del Cerro Piche', -40.67055, -68.38611, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp24588.html'),
    (24604, 'Ana María', -41.30333, -65.73, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp24604.html'),
    (24864, 'La Gaucha', -32.03916, -64.74527, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp24864.html'),
    (24868, 'La Mabel', -32.04555, -64.74027, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp24868.html'),
    (24870, 'La Belgica', -32.05027, -64.74972, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp24870.html'),
    (24871, 'La Belgica', -32.05027, -64.74972, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp24871.html'),
    (24890, 'La Jetona II', -32.08083, -64.905, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp24890.html'),
    (24891, 'La Lomita', -32.08638, -65.02861, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp24891.html'),
    (24893, 'La Felicidad (N y O)', -32.10444, -64.92194, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp24893.html'),
    (25016, 'La Esperanza', -32.06694, -64.42527, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp25016.html'),
    (25017, 'La Escombrera', -32.07, -64.40583, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp25017.html'),
    (25478, 'Cajón de Piedra; La Bandera', -40.63777, -65.83777, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp25478.html'),
    (25484, 'Blanquita', -41.01777, -67.81055, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp25484.html'),
    (25497, 'Amanda', -40.87333, -68.20138, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp25497.html'),
    (25501, 'Albafeld', -41.04388, -68.40611, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp25501.html'),
    (25621, 'La Chúcura', -31.35138, -63.61666, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp25621.html'),
    (25622, 'La Esperanza', -31.1025, -64.22305, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp25622.html'),
    (25623, 'La Floresta', -31.44638, -64.00694, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp25623.html'),
    (25638, 'Jerusalén', -31.22166, -64.27944, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp25638.html'),
    (25641, 'Juan Manuel', -31.32388, -64.42277, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp25641.html'),
    (25643, 'La Juanita', -31.49527, -64.45861, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp25643.html'),
    (25651, 'La Graciela', -31.235, -64.49305, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp25651.html'),
    (25670, 'Ing. Anibal Montes', -31.15638, -64.42555, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp25670.html'),
    (25698, 'La Calera', -30.17083, -64.44333, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp25698.html'),
    (25711, 'La Maroma', -30.55444, -64.03694, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp25711.html'),
    (25715, 'La Isabela', -30.6, -64.02805, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp25715.html'),
    (25722, 'Ischilín', 0.0, -64.33166, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp25722.html'),
    (25766, 'La Lina; La Playa', -30.99722, -65.3625, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp25766.html'),
    (26143, 'Mina Aída Rosa', -31.89333, -64.66194, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26143.html'),
    (26144, 'Río Oleayoc; Mina Herrana', -22.57888, -66.17111, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26144.html'),
    (26145, 'Río Herrana; Mina Oratorio', -22.58888, -66.19666, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26145.html'),
    (26146, 'Río Peñas Blancas; Mina Lipiara', -22.61083, -66.14861, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26146.html'),
    (26147, 'Río Lopiara; Mina San Telmo', -22.64166, -66.185, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26147.html'),
    (26148, 'Río San José; Mina San Ramón', -22.65138, -66.19333, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26148.html'),
    (26149, 'Veta del Contrabandista', -23.77888, -65.50222, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26149.html'),
    (26150, 'Mina Tacurú', -32.01111, -64.45027, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26150.html'),
    (26151, 'Mina Rita', -32.08861, -64.47, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26151.html'),
    (26152, 'Mina Estrella Gaucha', -32.31888, -64.52472, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26152.html'),
    (26153, 'Blancaflor', -23.32222, -65.73999, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26153.html'),
    (26154, 'Cerro Morro Este', -33.14333, -65.38111, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26154.html'),
    (26155, 'Bosque Alegre', -31.58166, -64.57388, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26155.html'),
    (26156, 'El Manzano; Blancaley', -31.98583, -64.4175, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26156.html'),
    (26157, 'Parador de la Montaña', -32.07833, -64.46611, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26157.html'),
    (26158, 'Los Cóndores', -32.32611, -64.31611, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26158.html'),
    (26159, 'Las Lajas', -30.70333, -64.62472, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26159.html'),
    (26160, 'Pampa de los Guanucos', -30.86638, -64.68305, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26160.html'),
    (26161, 'El Centenario; Estancia El Potrerillo; Los Troncos', -30.99944, -64.52972, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26161.html'),
    (26162, 'Los Guindos', -31.19222, -64.58166, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26162.html'),
    (26163, 'Los Oscuritos', -31.18666, -64.5975, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26163.html'),
    (26164, 'San Javier', -31.19416, -64.595, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26164.html'),
    (26165, 'Los Algarrobitos', -31.18694, -64.60027, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26165.html'),
    (26166, 'Cantera Tres Campanas', -31.15638, -64.59055, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26166.html'),
    (26167, 'La Providencia', -31.16305, -64.59638, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26167.html'),
    (26168, 'San Jorge', -31.13666, -64.5875, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26168.html'),
    (26169, 'Norberto Nieto; Cabadas', -31.10055, -64.54527, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26169.html'),
    (26170, 'Cantera Valle Hermoso ; San Antonio', -31.11361, -64.50583, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26170.html'),
    (26171, 'La Higuera; San Carlos', -31.05472, -65.02944, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26171.html'),
    (26172, 'El Cóndor', -31.12805, -64.77888, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26172.html'),
    (26173, 'Corral de Carnero', -31.13527, -64.79861, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26173.html'),
    (26174, 'El Saucecito', -31.09166, -64.80138, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26174.html'),
    (26175, 'Los Azulejos', -31.085, -64.68444, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26175.html'),
    (26176, 'Iggam', -31.27611, -64.81444, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26176.html'),
    (26177, 'Sarría Deheza; Los Cienegueros', -31.28972, -64.82444, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26177.html'),
    (26178, 'Ledesma', -31.26111, -64.85055, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26178.html'),
    (26179, 'El Divisadero', -31.23722, -64.80416, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26179.html'),
    (26180, 'La Quebrada', -31.21222, -64.79527, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26180.html'),
    (26181, 'El Balcón', -31.20361, -64.81694, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26181.html'),
    (26182, 'El Pantano', -31.18861, -64.82027, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26182.html'),
    (26183, 'Piedra Azul', -31.18555, -64.80222, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26183.html'),
    (26184, 'Cuchi Yaco', -31.32833, -65.03333, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26184.html'),
    (26185, 'Sagrada Familia', -31.36333, -65.03138, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26185.html'),
    (26186, 'Brillbauber', -31.37194, -65.0575, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26186.html'),
    (26187, 'Atos Pampa', -31.98416, -64.72555, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26187.html'),
    (26188, 'Los Cocos', -32.47666, -64.68416, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26188.html'),
    (26189, 'Achiras', -33.14444, -64.95361, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26189.html'),
    (26190, 'Rumi Huasi', -31.09777, -65.24944, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26190.html'),
    (26191, 'Santa Helena', -31.08277, -65.36277, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26191.html'),
    (26192, 'Ojo de Agua', -31.22027, -65.23277, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26192.html'),
    (26193, 'Arenera Cervín', -31.4975, -60.43277, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26193.html'),
    (26194, 'Cantera Tres Quebrachos', -31.61083, -60.32166, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26194.html'),
    (26195, 'Cantera s/n', -31.62111, -60.34166, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26195.html'),
    (26196, 'Arenera De La Cruz y Rozas S.A.', -31.64361, -60.68638, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26196.html'),
    (26197, 'Arenera Del Litoral S.R.L.', -31.64555, -60.68944, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26197.html'),
    (26198, 'Arenera Puerto Santa Fe S.R.L.', -31.64611, -60.69027, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26198.html'),
    (26199, 'Arenera Colastiné Sur', -31.66083, -60.60055, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26199.html'),
    (26200, 'Arenera Toma Nueva S.R.L.', -31.70583, -60.49472, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26200.html'),
    (26201, 'Langbein Guillermo Gustavo', -32.61444, -60.17583, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26201.html'),
    (26202, 'Puerto Campichuelo NO', -32.68583, -58.20083, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26202.html'),
    (26203, 'Cantera Aresil S.A.', -32.68916, -58.18805, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26203.html'),
    (26204, 'Cantera La Milagrosa; Puerto Campichuelo; San Marcos Trading S.A.', -32.70888, -58.18305, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26204.html'),
    (26205, 'Arenas Vignaduzzi S.R.L.', -32.80722, -60.70694, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26205.html'),
    (26206, 'Arenera Baigorria S.R.L.', -32.85083, -60.69555, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26206.html'),
    (26207, 'Arenera De La Cruz y Rozas S.A.', -32.86388, -60.69083, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26207.html'),
    (26208, 'Arenas Vignaduzzi S.R.L.', -33.05722, -60.57222, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26208.html'),
    (26209, 'Santa Rosa Arenas', -33.06166, -60.57, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26209.html'),
    (26210, 'Arenera Pueblo Esther S.R.L.', -33.06361, -60.56805, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26210.html'),
    (26211, 'Arenas Alzúa', -33.07166, -60.56138, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26211.html'),
    (26212, 'Arenas Bajo Paraná', -33.13055, -60.50888, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26212.html'),
    (26213, 'Arenas Sodini S.R.L.', -33.14666, -60.48277, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26213.html'),
    (26214, 'Arenera Rivadavia', -33.21888, -60.33222, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26214.html'),
    (26215, 'Punta Caballos', -33.29527, -58.46694, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26215.html'),
    (26216, 'Arenera San Nicolás', -33.34972, -60.18111, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26216.html'),
    (26217, 'Arenera del Puerto S.A.', -33.68583, -59.64222, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26217.html'),
    (26218, 'San Pedro Arenas S.A.', -33.69583, -59.63361, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26218.html'),
    (26219, 'Empresa Sposito S.A.; Sucursal Río Tala', -33.74333, -59.60361, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26219.html'),
    (26220, 'Arenera Harrow', -33.90777, -58.8925, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26220.html'),
    (26221, 'Arenas de Cercanía S.A.', -37.40944, -68.90111, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26221.html'),
    (26222, 'Flint Sand', -39.00916, -67.98555, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26222.html'),
    (26223, 'El Motivo; SO de Allen', -39.02138, -67.895, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26223.html'),
    (26224, 'CIMSA', -39.32944, -67.35638, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26224.html'),
    (26225, 'Aluvional - Vista Oil', -39.35722, -67.11055, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26225.html'),
    (26226, 'Uan (Ciccarelli)', -39.38333, -67.22861, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26226.html'),
    (26227, 'Bauti', -39.78027, -67.24722, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26227.html'),
    (26228, 'Vale', -39.94333, -68.81138, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26228.html'),
    (26229, 'CIMSA RN1', -39.99972, -66.97222, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26229.html'),
    (26230, 'Franca', -40.00027, -66.87361, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26230.html'),
    (26231, 'Luz', -40.03555, -66.95083, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26231.html'),
    (26232, 'Negro', -40.0525, -66.96638, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26232.html'),
    (26233, 'Corral de Piedra', -40.56055, -68.63083, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26233.html'),
    (26234, 'Doña Elisa', -40.76361, -68.56972, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26234.html'),
    (26235, 'Lenza', -40.80749, -68.71888, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26235.html'),
    (26236, 'La Esperanza', -43.02416, -66.46055, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26236.html'),
    (26237, 'La Picada', -43.18333, -66.69416, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26237.html'),
    (26238, 'Grupo Arenas Patagónicas Dolavon', -43.30333, -65.74027, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26238.html'),
    (26239, 'Tordillos', -38.55638, -69.25111, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26239.html'),
    (26240, 'Cerro Mesa', -38.68388, -69.5925, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26240.html'),
    (26242, 'Santo Domingo', -32.94583, -65.91277, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26242.html'),
    (26243, 'Almirante Brown', -32.97916, -65.96777, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26243.html'),
    (26244, '6 de septiembre', -32.98638, -65.97555, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26244.html'),
    (26245, 'Grupo Aurora', -30.64972, -67.58027, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26245.html'),
    (26246, 'Abra de Minas', -23.36472, -65.00388, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26246.html'),
    (26247, 'Veta Encrucijada', -23.405, -65.22555, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26247.html'),
    (26248, 'Telar Cueva; Cueva del Tigre; La Hilaria', -23.40805, -66.32833, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26248.html'),
    (26249, 'Barda Negra', -39.18944, -69.68, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26249.html'),
    (26250, 'Cantera San Francisco', -39.18944, -65.50944, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26250.html'),
    (26251, 'Cerro Orcona', -22.59777, -65.56027, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26251.html'),
    (26252, 'Pedro Nicolás', -25.545, -65.95416, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26252.html'),
    (26253, 'Martín Miguel de Güemes', -25.34277, -65.95027, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26253.html'),
    (26254, 'Emmy', -25.69222, -65.84472, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26254.html'),
    (26255, 'Sunchales Este', -25.64777, -65.91416, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26255.html'),
    (26256, 'Pepe Luis', -25.59277, -65.9575, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26256.html'),
    (26257, 'Cuesta de Bala', -25.54555, -65.95861, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26257.html'),
    (26258, 'El Leñadero', -25.64722, -65.88944, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26258.html'),
    (26259, 'El Desecho', -25.66611, 0.0, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26259.html'),
    (26260, 'Costa de Isonza', -25.38527, -65.88805, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26260.html'),
    (26261, 'Cajoncillo', -25.69027, -65.83444, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26261.html'),
    (26262, 'Providencia', -25.1775, -65.855, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26262.html'),
    (26263, 'La Despedida; Las Juntas', -25.78944, -65.56111, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26263.html'),
    (26264, 'Quebrada Varita - Las Vacas; Troya; Área de Reserva N°4 Plan La Rioja', -29.20833, -68.92666, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26264.html'),
    (26265, 'La Quinta', -23.88361, -64.46555, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26265.html'),
    (26266, 'Azufrera de Santa Bárbara', -23.88527, -64.46611, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26266.html'),
    (26267, 'Arroyo Santa Bárbara', -24.32527, -64.48611, 'https://sigam.segemar.gov.ar/segedoc/res/img/sigam_yacimientos/dp26267.html')
  ) AS v(depno, name, lat, lon, url)
  RETURNING locationid, external_id
)
INSERT INTO deposits (locationid, deposit_type_id, deposit_type_local, deposit_status,
                      size_category, geological_province, tectonic_setting, mineralization_style,
                      deposit_form, alteration, metallogenic_association, associated_igneous,
                      "references", comments, createdby)
SELECT nl.locationid, v.dt_id, v.dt_local, v.status, v.size_cat, v.prov, v.tect, v.mstyle,
       v.form, v.alt, v.meta, v.ign, v.refs, v.com, 'claude_sigam_20260910'
FROM nl JOIN (VALUES
    (239, 132, '06j Pb-Zn-Ag-Cu', 'OCCURRENCE', 'UNKNOWN', 'Sierras Pampeanas', 'continental (roca huésped)', 'vetiforme', NULL, NULL, 'Pb-Ag-Zn', '(1) intrusiva; suite granítica', 'Godeas, M; Cardó, R; Carrizo, R; Cruz Zuloeta, G; González, R; Korzeniewski, L; López, H; Malimacci, H; Martínez, L; Ramallo, E; Valladares, H; Zubia, M, 1999
Inventario de Yacimientos y Manifestaciones de Minerales Metalíferos e Industriales de la República Argentina
Recursos Minerales de la República Argentina, Volume II', NULL),
    (240, 132, '06j Pb-Zn-Ag-Cu', 'OCCURRENCE', 'UNKNOWN', 'Sierras Pampeanas', 'continental (roca huésped)', 'vetiforme', NULL, NULL, 'Pb-Ag', NULL, 'Godeas, M; Cardó, R; Carrizo, R; Cruz Zuloeta, G; González, R; Korzeniewski, L; López, H; Malimacci, H; Martínez, L; Ramallo, E; Valladares, H; Zubia, M, 1999
Inventario de Yacimientos y Manifestaciones de Minerales Metalíferos e Industriales de la República Argentina
Recursos Minerales de la República Argentina, Volume II', NULL),
    (243, 132, '06j Pb-Zn-Ag-Cu', 'CLOSED', 'SMALL', 'Sierras Pampeanas', 'continental arco (roca huésped)', 'vetiforme', NULL, NULL, 'Pb - Zn - Ag - Au', '(1) intrusiva; suite granítica', 'Angelelli, V, 1984
Yacimientos Metalíferos de la República Argentina II
Comisión de Investigaciones Científicas de la provincia de Buenos Aires, Facultad de Ciencias Naturales y Museo de La Plata-, 311 p.

Candiani, J.C; Segal, S; Miró, R; Cucchi, R, 1993
Estudio Geológico y Evaluación Económica de la mina La Argentina, Córdoba, Argentina
VI Congreso Colombiano de Geología, Volume II, p. 557 - 568

Cardó, Raúl; Segal, Susana; Zubia, Mario, 2004
Descripción del Mapa metalogenético del oro de la República Argentina
Recursos de Oro de la Argentina, p. - 93

Olsacher, J, 1960
Descripción geológica de la hoja 20h Los Gigantes, provincia de Córdoba.DNGM.Boletín 90
Hojas Geológicas de la República Argentina Escala 1:200000', NULL),
    (264, 132, '06j Pb-Zn-Ag-Cu', 'OCCURRENCE', 'UNKNOWN', 'Sierras Pampeanas', 'continental (roca huésped)', 'vetiforme', NULL, NULL, 'Pb - Zn - Ag', '(1) intrusiva; suite granítica', 'Skirrow, R; López, H, 2001
Recursos minerales en Hoja Geológica 3166-II Cruz del Eje, provincia de Córdoba, La Rioja y Catamarca
Hojas Geológicas escala 1:100000.', NULL),
    (268, 132, '06j Pb-Zn-Ag-Cu', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', 'continental (roca huésped)', 'vetiforme', NULL, 'sericita pirítica', 'Zn-Pb-Ag', '(1) intrusiva; suite granítica', 'Skirrow, R; López, H, 2001
Recursos minerales en Hoja Geológica 3166-II Cruz del Eje, provincia de Córdoba, La Rioja y Catamarca
Hojas Geológicas escala 1:100000.', NULL),
    (270, 132, '06j Pb-Zn-Ag-Cu', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', 'continental (roca huésped)', 'vetiforme', NULL, NULL, 'Pb - Zn - Ag', '(1) intrusiva; suite granítica', 'Skirrow, R; López, H, 2001
Recursos minerales en Hoja Geológica 3166-II Cruz del Eje, provincia de Córdoba, La Rioja y Catamarca
Hojas Geológicas escala 1:100000.', NULL),
    (271, 132, '06j Pb-Zn-Ag-Cu', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', 'continental (roca huésped)', 'vetiforme', NULL, NULL, 'Pb - Zn - Ag', '(1) intrusiva; suite granítica', 'Skirrow, R; López, H, 2001
Recursos minerales en Hoja Geológica 3166-II Cruz del Eje, provincia de Córdoba, La Rioja y Catamarca
Hojas Geológicas escala 1:100000.', '(APPLIESTO: Mineralización) Las labores australes se denominan Overo Muerto y tienen una mena muy argentífera'),
    (272, 132, '06j Pb-Zn-Ag-Cu', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', 'continental (roca huésped)', 'vetiforme', NULL, NULL, 'Pb - Zn - Ag', '(1) intrusiva; suite granítica', 'Skirrow, R; López, H, 2001
Recursos minerales en Hoja Geológica 3166-II Cruz del Eje, provincia de Córdoba, La Rioja y Catamarca
Hojas Geológicas escala 1:100000.', NULL),
    (273, 132, '06j Pb-Zn-Ag-Cu', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', 'continental (roca huésped)', 'vetiforme', NULL, NULL, 'Pb - Zn - Ag', '(1) intrusiva; suite granítica', 'Skirrow, R; López, H, 2001
Recursos minerales en Hoja Geológica 3166-II Cruz del Eje, provincia de Córdoba, La Rioja y Catamarca
Hojas Geológicas escala 1:100000.', NULL),
    (287, 132, '06j Pb-Zn-Ag-Cu', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', 'continental (roca huésped)', 'vetiforme', NULL, NULL, 'Pb - Zn - Ag', '(1) intrusiva; suite granítica', 'Lyons, P; Skirrow, R, 1997
Report on 1:100000 scale geological and metallogenic maps. Sheet 3166-17, province of Cordoba. Mapa Geocientífico de Sierras Pampeanas. Proyecto de Cooperación Argentino-Australiano.IGRM.SEGEMAR. Boletín 238', NULL),
    (510, 132, '14c Polimetálicos simples (Pb-Zn-Ag (+-Au-Ba))', 'OCCURRENCE', 'UNKNOWN', 'Precordillera Patagónica', 'continental arco (roca huésped)', 'vetiforme', NULL, 'cuarzo-sericítica silicificación', 'Pb - Zn', '(1) intrusiva; suite graníticaLitologías individuales:granodiorita', 'Herrero, J.C, 1978
Informe preliminar de parte de los mosaicos 4172-IV-B1,B2,C1,C2 Proyectos 15 AL Lago Mascardi y 15AM El Bolsón. Plan Patagonia Comahue', '(APPLIESTO: Geoquímica) En sedimentos fluviales se detectaron anomalías de: Pb hasta 106 ppm y de Zn de hasta 100 ppm'),
    (2095, 65, '07a Manganeso (Mn+-F)', 'PAST_PRODUCER', 'SMALL', 'Sierras Pampeanas', 'continental rift cretácico; extensional (Fallas-fisuras)', 'vetiforme', NULL, NULL, 'Br, As, Cs, U (Cu, Zn)', NULL, 'Angelelli, Victorio, 1984
Yacimientos Metalíferos de la República Argentina, Tomo 1
Comisión de Investigaciones Científicas de la provincia de Buenos Aires, 704 p.

Bianchi, Angel; Rivera, José, 1959
Estudio geológico económico preliminar de los yacimientos de mineral de manganeso de pedanía Aguada del Monte, departamento Sobremonte, Córdoba. Distrito Pozo Nuevo, zona Norte.
Dirección provincial de Minería. Córdoba., Inédito

Elizalde, César; González Laguinge, H., 1957
Informe final acerca de las labores, muestreo y cubicación realizados en los yacimientos de manganeso y hierro de Aguada del Monte (Grupo Hiermang), departamento Sobremonte, provincia de Córdoba.
Dirección General de Fabricaciones Militares

Fernández Aguilar, Rafael, 1942
Yacimientos de manganeso de Aguada del Monte, departamento Sobremonte, Córdoba.
Dirección de Minería y Geología, Inédito

López, Hector; Brodtkorb, Milka; Brodtkorb, Alejo, 2009
Carta Minero-Metalogenética 2963-III Villa Ojo de Agua, provincias de Santiago del Estero y Córdoba
Carta Minero-Metalogenética al 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina., Volume 376

Padula, Vicente, 1966
Reconocimiento general del distrito manganesífero del sur de Santiago del Estero y norte de Córdoba con vistas a la instalación de plantas regionales de beneficio. Muestreo para ensayos de concentración. Consideraciones económicas preliminares.
Instituto Nacional de Geología y Minería, Inédito, 73 p., 2 maps.', '(APPLIESTO: mineralization) Las vetas tienen una morfolgía brechosa y sus clastos corresponden a las cajas granodioríticas con minerales de manganeso como cemento (López et al. 2009). En 12 de octubre, se observa que la veta tiene rumbo NO; en La Esperanza se observa rumbo general N-S (Angelelli 1984).'),
    (2199, 65, '07a Manganeso (Mn+-F)', 'OCCURRENCE', 'OCCURRENCE', 'Engolfamiento Neuquino', NULL, 'irregular, estratoligada', NULL, NULL, NULL, NULL, 'González, Rafael; Espejo, Patricia, 2001
Recursos Naturales de la Hoja Geológica 3966-III "Villa Regina", provincia de Río Negro
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 309

Gonzalez Amorin, Rodolfo; Soto, Adrian, 1951
Informe sobre las manifestaciones manganíferas de la mina "Aurora", dpto. Gral. Roca, Terr. Nac. de Río Negro
DGFM, Inédito, Publication code 148, 5 p., 2 maps.', NULL),
    (4007, 164, '06a Granitoides (W-Mo); se asimila al depósito Panasqueiras de Portugal', 'CLOSED', 'SMALL', 'Sierras pampeanas orientales', 'continental arco-arco (roca huésped)', 'vetas', NULL, 'fluoritización; Qué fue alterado: vetas turmalinización; Qué fue alterado: vetas pirítica sillicificación', 'W Bi', '(1) intrusiva; suite granítica', 'Fernández, Raúl, 1999
El distrito minero La Bismutina
Recursos Minerales de la República Argentina, p. 443 - 448', NULL),
    (5105, 164, '06a Granitoides (W-Mo)', 'PAST_PRODUCER', 'OCCURRENCE', 'Sierras Pampeanas', 'arcos de islas (rocas de caja)', 'mantos (zona mineralizada principal)', NULL, NULL, 'W', '(1) intrusiva; granito; Fecha de actualización: Stock San José; Serie magmática: calcoalcalino; COMPONENT: zona mineralizada principalLitologías individuales:granito', 'Ametrano, S., 1997
Los yacimientos de tungsteno de la sierra de Altautina, provincia de Córdoba
Universidad Nacional de La Plata. Tesis Doctoral. Inédito

Ametrano , Silvia, 1999
El distrito scheelítico de la sierra de Altautina, Córdoba
Anales del Servicio Geológico Minero Argentino, Volume I, p. 233 - 239

Angelelli, Victorio, 1984
Yacimientos metalíferos de la República Argentina. Tomos I y II
Comisión de Investigaciones Científicas. Provincia de Buenos Aires. CIC, 704 p.

Brodtkorb, Milka K. de; Pezzutti, Norma E., 1991
Yacimientos scheelíticos en rocas calcosilicáticas asociados a anfibolitas. Provincias de San Luis y Córdoba
Instituto de Recursos Minerales - Universidad Nacional de La Plata, p. 169 - 184', '(APPLIESTO: mineralización) Según Ametrano (1997, 1999), la scheelita es de tipo II (en vetas) y estaría relacionada con el stock SanJosé. Datos de corrida y potencia de La Dita según Angelelli (1984)'),
    (5126, 116, '08f Volcanogénico (W)', 'PAST_PRODUCER', 'SMALL', 'Sierras Pampeanas', 'arcos de islas (roca ignea relaciona)', 'diseminada (zona mineralizada principal); vetiforme (zona mineralizada principal)', NULL, NULL, 'W', '(1) volcánica; basaltos tholeíiticos; Serie magmática: tholeiítico; COMPONENT: zona mineralizada principalLitologías individuales:basaltos tholeíticos', 'Brodtkorb, Milka K. de; Pezzutti, Norma E., 1991
Yacimientos scheelíticos en rocas calcosilicáticas asociados a anfibolitas. Provincias de San Luis y Córdoba
Instituto de Recursos Minerales - Universidad Nacional de La Plata, p. 169 - 184

Gamba, María T., 1999
Distrito scheelítico Pampa de Olaen, Córdoba
Anales del Servicio Geológico Minero Argentino, Volume I, p. 251 - 256', NULL),
    (5136, 116, '08f Volcanogénico (W)', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', 'arcos de islas (roca ignea relaciona)', 'vetiforme (zona mineralizada principal)', NULL, NULL, 'W', '(1) volcánica; Serie magmática: tholeiítico; COMPONENT: zona mineralizada principal', 'Godeas, Marta; Cardó, Raúl; Carrizo, Ramón; Cruz Zuloeta, , Gonzalo; González (h), Rafael; Korzeniewski, Lidia I.; López, Héctor; Mallimacci, Hugo; Martínez, Liliana; Ramallo, Eulogio; Valladares, Hildebrando; Zubia, Mario, 1999
Inventario de yacimientos y manifestaciones de minerales metalíferos e industriales de la República Argentina. Recursos Minerales de la República Argentina (Ed. E. O. Zappettini). Instituto de Geología y Recirsos Minerales, Anales 35
Anales del Servicio Geológico Minero Argentino, Volume II, p. 1979 - 2172', NULL),
    (5137, 116, '08f Volcanogénico (W)', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', 'arcos de islas (roca ignea relaciona)', 'vetiforme (zona mineralizada principal)', NULL, NULL, 'W', '(1) volcanica; basaltos tholeiíticos; Serie magmática: tholeiítico; COMPONENT: zona mineralizada principalLitologías individuales:basaltos tholeíticos', 'Godeas, Marta; Cardó, Raúl; Carrizo, Ramón; Cruz Zuloeta, , Gonzalo; González (h), Rafael; Korzeniewski, Lidia I.; López, Héctor; Mallimacci, Hugo; Martínez, Liliana; Ramallo, Eulogio; Valladares, Hildebrando; Zubia, Mario, 1999
Inventario de yacimientos y manifestaciones de minerales metalíferos e industriales de la República Argentina. Recursos Minerales de la República Argentina (Ed. E. O. Zappettini). Instituto de Geología y Recirsos Minerales, Anales 35
Anales del Servicio Geológico Minero Argentino, Volume II, p. 1979 - 2172', NULL),
    (5138, 116, '08f Volcanogénico (W)', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', 'arcos de islas (roca ignea relaciona)', 'vetiforme (zona mineralizada principal)', NULL, NULL, 'W', '(1) volcánica; basaltos tholeiíticos; Serie magmática: tholeiítico; COMPONENT: zona mineralizada principalLitologías individuales:basaltos tholeíticos', 'Godeas, Marta; Cardó, Raúl; Carrizo, Ramón; Cruz Zuloeta, , Gonzalo; González (h), Rafael; Korzeniewski, Lidia I.; López, Héctor; Mallimacci, Hugo; Martínez, Liliana; Ramallo, Eulogio; Valladares, Hildebrando; Zubia, Mario, 1999
Inventario de yacimientos y manifestaciones de minerales metalíferos e industriales de la República Argentina. Recursos Minerales de la República Argentina (Ed. E. O. Zappettini). Instituto de Geología y Recirsos Minerales, Anales 35
Anales del Servicio Geológico Minero Argentino, Volume II, p. 1979 - 2172', NULL),
    (5233, 164, '06a Granitoides (W-Mo)', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', 'arco -arco (roca ignea relaciona)', 'diseminada (zona mineralizada principal)', NULL, NULL, 'W (Cu-Pb-Zn)', '(1) intrusiva; suite granítica; Serie magmática: calcoalcalino; COMPONENT: zona mineralizada principalLitologías individuales:granito', 'Servicio Nacional Minero Geológico, 1972
Exploración Geológico-Minera del Noroeste Argentino. NOA I (Área Tucumán-Catamarca-Santiago del Estero). Subsecretaría de Minería
Servicio Nacional Minero Geológico, p. 3 - 115', NULL),
    (11168, 21, '13f Bentonita', 'PRODUCER', 'MEDIUM', 'Engolfamiento Neuquino', 'oceánico cuenca-retroarco (rocas huésped)', 'capas', NULL, NULL, NULL, NULL, 'Gozalvez, Martín; Herrmann, Carlos; Zappettini, Eduardo, 2004
Minerales Industriales de La República Argentina
Anales del Servicio Geológico Minero Argentino, p. 76 - 78

Valles, Jorge; Impiccini, Agnes, 1999
Bentonitas de la Cuenca Neuquina Río Negro, Neuquén y La Pampa
Anales del Servicio Geológico Minero Argentino, Volume 35, p. 1113 - 1125', NULL),
    (11175, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'PRODUCER', 'MEDIUM', 'Sierras Pampeanas', NULL, 'mantos', NULL, NULL, NULL, NULL, 'Sfragulla, Jorge; Jerez, Daniel; Bonalumi, Aldo, 1999
Mármoles y otras rocas caqrbonáticas de Córdoba
Anales del Servicio Geológico Minero Argentino, Volume 35, p. 271 - 295', NULL),
    (11261, 53, '09f Evaporitas Lacustres,Yeso-Halita-Silvita-Boratos-Sulfatos(MgKCaLi)', 'PRODUCER', 'SMALL', 'Sierras Subandinas', 'continental-no calificado; convergente (rocas huésped)', 'lentes', NULL, NULL, NULL, NULL, 'Gamundi, Carlos; Martensen, Julio, 1999
Yacimientos de yeso de Tucumán
Anales del Servicio Geológico Minero Argentino, Volume 35, p. 1761 - 1767', NULL),
    (11358, 88, '14f Au en zonas de cizalla (Au-Ag-As-Cu)', 'UNKNOWN', 'SMALL', 'Sierras Pampeanas', 'continental arco (rocas huésped)', 'vetas y venillas de sulfuros-Au', NULL, NULL, 'Pb-Zn-Ag', '(1) intrusiva; suite granítica', 'Cardó, Raúl; Segal, Susana; Zubia, Mario, 2004
Descripción del Mapa Metalogenético del Oro en la República Argentina
Instituo de Geología y Recursos Minerales, Anales 38, CD-ROM', NULL),
    (24561, 35, '09b U-Cu en areniscas (U-V-Cu-Ag)', 'EXPLORATION', 'UNKNOWN', 'Macizo Nordpatagónico', NULL, 'U-V-(Cu) en areniscas', NULL, 'oxidación; Qué fue alterado: roca de caja decoloración; Qué fue alterado: roca de caja', 'U-V', NULL, NULL, NULL),
    (24581, 118, '07b Au baja sulfuración (Adularia) (Au-Ag)', 'EXPLORATION', 'MEDIUM', 'Macizo Nordpatagónico', NULL, 'vetiforme', NULL, 'silícica; Qué fue alterado: roca de caja argílica; Qué fue alterado: roca de caja sericítica; Qué fue alterado: roca de caja propilítica; Qué fue alterado: roca de caja', 'Au-Ag', '(1) volcanica; rocas volcánicas intermedias-félsicas', 'Cardó, Raúl; Segal, Susana; Zubia, Mario, 2004
Descripción del Mapa Metalogenético del Oro en la República Argentina
Instituo de Geología y Recursos Minerales, Anales 38, CD-ROM', NULL),
    (24582, 118, '07b Au baja sulfuración (Adularia) (Au-Ag)', 'EXPLORATION', 'MEDIUM', 'Macizo Nordpatagónico', NULL, 'vetas', NULL, 'silícica; Qué fue alterado: roca de caja argílica sericítica; Qué fue alterado: roca de caja propilítica; Qué fue alterado: roca de caja', 'Au-Ag', '(1) volcánica; rocas volcánicas intermedias-félsicas', 'Cardó, Raúl; Segal, Susana; Zubia, Mario, 2004
Descripción del Mapa Metalogenético del Oro en la República Argentina
Instituo de Geología y Recursos Minerales, Anales 38, CD-ROM', NULL),
    (24588, 35, '09b U-Cu en areniscas (U-V-Cu-Ag)', 'PROSPECT', 'UNKNOWN', 'Macizo Nordpatagónico', NULL, 'horizontes', NULL, NULL, 'U', NULL, NULL, NULL),
    (24604, 119, '07e Polimetálico complejo (Pb-Ag-Zn-Cu (±Au±Sb±Bi±W)', 'PROSPECT', 'UNKNOWN', 'Macizo Nordpatagónico', NULL, 'vetiforme', NULL, 'silícea; Qué fue alterado: roca de caja', 'Pb - Zn - Ag', NULL, NULL, NULL),
    (24864, NULL, '01f Ornamentales(Gabro, Ultramafitítas-Verde Alpes)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (24868, NULL, '01f Ornamentales(Gabro, Ultramafitítas-Verde Alpes)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (24870, NULL, '01f Ornamentales(Gabro, Ultramafitítas-Verde Alpes)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (24871, 189, '10e Talco-Asbesto(Pirofilita)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (24890, 169, '03a Pegmatitas Complejas(Be-Li-Aguamarina)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (24891, 169, '03a Pegmatitas Complejas(Be-Li-Aguamarina)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (24893, 169, '03a Pegmatitas Complejas(Be-Li-Aguamarina)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (25016, 21, '13b Vermiculita', 'PRODUCER', 'SMALL', 'Sierras Pampenas Orientales', NULL, 'fajas', NULL, NULL, NULL, NULL, NULL, NULL),
    (25017, 21, '13b Vermiculita', 'PRODUCER', 'SMALL', 'Sierras Pampenas Orientales', NULL, 'fajas', NULL, NULL, NULL, NULL, NULL, NULL),
    (25478, 21, '09m Arcillas', 'UNKNOWN', 'UNKNOWN', 'Macizo Nordpatagónico', NULL, NULL, NULL, NULL, NULL, NULL, 'Martínez, Héctor; Náñez, Carolina; Lizuain, Antonio; Dal Molin, Carlos; Turel, Andrea, 2001
Hoja Geológica 4166-II, San Antonio Oeste, provincia de Río Negro. Boletín N° 254.
Instituto de Geología y Recursos Minerales, Servicio Geológico Minero Argentino, 38 p.', NULL),
    (25484, 21, '07i Caolín-Bentonita', 'PAST_PRODUCER', 'MEDIUM', 'Macizo Nordpatagónico', NULL, NULL, NULL, NULL, NULL, NULL, 'Godeas, M.; Cardó, R.; Carrizo, R.; Cruz Zuloeta, G.; González (h), R.; Korzeniewski, L.; López, H.; Mallimacci, H.; Martínez, L.; Ramallo, E.; Valladares, H.; Zubia, M., 1999
Inventario de yacimientos y manifestaciones de minerales metalíferos e industriales de la República Argentina. En: Recursos Minerales de la República Argentina. (Ed. E. O. Zappettini). Anales 35
Anales del Servicio Geológico Minero Argentino, Volume II, p. 1978 - 2172

Gozalvez, Martín; Herrmann, Carlos; Zappettini, Eduardo, 2004
Minerales Industriales de La República Argentina
Anales del Servicio Geológico Minero Argentino, p. 76 - 78

Remesal, Marcela; Salani, Flavia; Ardolino, Alberto; Dalponte, Marcelo; Espejo, Patricia, 2001
Hoja Geológica 4169-IV, Maquinchao, provincia de Río Negro. Boletín N° 312.
Instituto de Geología y Recursos Minerales, Servicio Geológico Minero Argentino, 74 p.', NULL),
    (25497, 21, '07i Caolín-Bentonita', 'UNKNOWN', 'UNKNOWN', 'Macizo Nordpatagónico', NULL, NULL, NULL, NULL, NULL, NULL, 'Cucchi, R; Busteros, A; Lema, H; Dalponte, M; Espejo, P, 2001
Hoja Geológica 4169-II Los Menucos, provincia de Río Negro SEGEMAR.IGRM', NULL),
    (25501, 21, '07i Caolín-Bentonita', 'UNKNOWN', 'UNKNOWN', 'Macizo Nordpatagónico', NULL, NULL, NULL, NULL, NULL, NULL, 'Remesal, Marcela; Salani, Flavia; Ardolino, Alberto; Dalponte, Marcelo; Espejo, Patricia, 2001
Hoja Geológica 4169-IV, Maquinchao, provincia de Río Negro. Boletín N° 312.
Instituto de Geología y Recursos Minerales, Servicio Geológico Minero Argentino, 74 p.', NULL),
    (25621, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (25622, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (25623, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (25638, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (25641, 168, '03c Pegmatitas Simples(Feldespato-Qz-Mica)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (25643, 168, '03c Pegmatitas Simples(Feldespato-Qz-Mica)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (25651, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (25670, 21, '13b Vermiculita', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (25698, NULL, '06f Rocas (Granitos, Sienitas, etc)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (25711, NULL, '06f Rocas (Granitos, Sienitas, etc)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (25715, NULL, '06f Rocas (Granitos, Sienitas, etc)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (25722, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (25766, 48, '07h Termal (Travertino-Boratos)', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'horizontes (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26143, 111, '08a VMS Máfico (tipo Cyprus)', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', 'no establecido rift-retroarco; divergente (mineralización)', 'masiva, diseminada (mineralización principal); masiva, vetillas (mineralización secundaria o supergénica)', NULL, NULL, 'Cu-Fe', NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26144, 3, '12a Au', 'UNKNOWN', 'SMALL', 'Puna', NULL, 'placeres aluviales (zona de mineralización principal)', NULL, NULL, 'Au', NULL, 'Morello, Carlos H., 2002
Evaluación Recursos Mineros Económicos de los aluviones auríferos del distrito Santa Domingo, Dpto. Rinconada, Provincia de Jujuy
Inédito', NULL),
    (26145, 3, '12a Au', 'UNKNOWN', 'SMALL', 'Puna', NULL, 'placer (zona mineralizada principal)', NULL, NULL, 'Au', NULL, 'Morello, Carlos H., 2002
Evaluación Recursos Mineros Económicos de los aluviones auríferos del distrito Santa Domingo, Dpto. Rinconada, Provincia de Jujuy
Inédito', NULL),
    (26146, 3, '12a Au', 'UNKNOWN', 'SMALL', 'Puna', NULL, 'placer (Zona principal de mineralización)', NULL, NULL, 'Au', NULL, 'Morello, Carlos H., 2002
Evaluación Recursos Mineros Económicos de los aluviones auríferos del distrito Santa Domingo, Dpto. Rinconada, Provincia de Jujuy
Inédito', NULL),
    (26147, 3, '12a Au', 'UNKNOWN', 'SMALL', 'Puna', NULL, 'placeres aluviales (zona mineralizada principal)', NULL, NULL, 'Au', NULL, 'Morello, Carlos H., 2002
Evaluación Recursos Mineros Económicos de los aluviones auríferos del distrito Santa Domingo, Dpto. Rinconada, Provincia de Jujuy
Inédito', NULL),
    (26148, 3, '12a Au', 'UNKNOWN', 'SMALL', 'Puna', NULL, 'placeres aluviales (zona mineralizada principal)', NULL, NULL, 'Au', NULL, 'Morello, Carlos H., 2002
Evaluación Recursos Mineros Económicos de los aluviones auríferos del distrito Santa Domingo, Dpto. Rinconada, Provincia de Jujuy
Inédito', NULL),
    (26149, 119, '07e Polimetálico complejo (Pb-Ag-Zn-Cu (±Au±Sb±Bi±W)', 'CLOSED', 'SMALL', 'Cordillera Oriental', NULL, 'vetiforme (zona mineralizada principal)', NULL, NULL, 'Cu-Pb', NULL, 'Ramos, M.C.; Iza, A., 1966
Informe del yacimiento dolomítico de Tumbaya, departamento Tumbaya, provincia de Jujuy.Informe inédito.
Dirección Provincial de Minería de Jujuy., 9 p.', NULL),
    (26150, 111, '08a VMS Máfico (tipo Cyprus)', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', 'rift-retroarco; divergente (mineralización)', 'lenticular (zona de mineralización principal); stockwork (zona de mineralización principal); vetiforme (zona de mineralización principal)', NULL, 'silicifiación biotitización epidotización cloritización', NULL, NULL, 'Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26151, 111, '08a VMS Máfico (tipo Cyprus)', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', 'rift-retroarco; divergente (mineralización)', 'lenticular (zona de mineralización principal); stockwork (zona de mineralización principal)', NULL, 'silicificación epidotización cloritización', 'Cu-Fe', NULL, 'Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26152, 111, '08a VMS Máfico (tipo Cyprus)', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'faja irregular (zona de mineralización principal); stockwork', NULL, 'silicificación epidotización albitización cloritización argilica', NULL, NULL, 'Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26153, 132, '14c Polimetálicos simples (Pb-Zn-Ag (+-Au-Ba))', 'CLOSED', 'OCCURRENCE', 'Puna', NULL, 'vetiforme (zona mineralizada principal)', NULL, NULL, 'Ba Pb', NULL, NULL, NULL),
    (26154, 116, '08f Volcanogénico (W)', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'diseminada (zona mineralizada principal)', NULL, NULL, 'W', NULL, 'Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26155, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'UNKNOWN', 'MEDIUM', 'Sierras Pampeanas', NULL, 'bancos', NULL, NULL, NULL, NULL, 'Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26156, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'PRODUCER', 'SMALL', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26157, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'UNKNOWN', 'SMALL', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26158, NULL, '10i Rocas(Pizarra-Mármol-Gneis); Mármol con tendencia dolomítica', 'CLOSED', 'SMALL', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26159, NULL, '10i Rocas(Pizarra-Mármol-Gneis); Mármol calcítico', 'UNKNOWN', 'SMALL', 'Sierras Pampeanas', NULL, NULL, NULL, NULL, NULL, NULL, 'Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26160, NULL, '10i Rocas(Pizarra-Mármol-Gneis); Mármol con tendencia calcítica', 'UNKNOWN', 'SMALL', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26161, NULL, '10i Rocas(Pizarra-Mármol-Gneis); Mármol calcítico', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos', NULL, NULL, NULL, NULL, 'Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26162, NULL, '10i Rocas(Pizarra-Mármol-Gneis); Mármol calcítico', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26163, NULL, '10i Rocas(Pizarra-Mármol-Gneis); Mármol calcítico', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26164, NULL, '10i Rocas(Pizarra-Mármol-Gneis); Mármol calcítico', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26165, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26166, NULL, '10i Rocas(Pizarra-Mármol-Gneis); Mármol calcítico', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26167, NULL, '10i Rocas(Pizarra-Mármol-Gneis); Mármol calcítico', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26168, NULL, '10i Rocas(Pizarra-Mármol-Gneis); Mármol calcítico', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26169, NULL, '10i Rocas(Pizarra-Mármol-Gneis); Mármol calcítico', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'mantiforme (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26170, NULL, '10i Rocas(Pizarra-Mármol-Gneis); Mármol calcítico', 'CLOSED', 'MEDIUM', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26171, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26172, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26173, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26174, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26175, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26176, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26177, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26178, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26179, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26180, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26181, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26182, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26183, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26184, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26185, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bochones (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26186, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', NULL, NULL, NULL, NULL, NULL, NULL, 'Bonalumi, Aldo; Martino, Ricardo; Baldo, Edgardo; Sfragulla, Jorge; Carignano, Claudio; Tauber, Adán; Zarco, Juan; Kraemer, Pablo; Escayola, Mónica, 1999
Hoja Geológica 3166-IV, Villa Dolores. Provincias de Córdoba, La Rioja y San Luis.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 250

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26187, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos lenticulares (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26188, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'mantiforme (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26189, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'mantiforme (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26190, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26191, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26192, NULL, '10i Rocas(Pizarra-Mármol-Gneis)', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26193, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26194, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26195, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26196, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26197, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26198, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26199, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26200, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26201, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26202, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26203, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26204, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26205, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26206, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26207, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26208, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26209, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26210, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26211, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26212, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26213, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26214, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26215, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26216, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26217, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26218, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26219, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26220, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26221, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26222, 11, '12g Aridos(Arenas-Gravas)', 'CLOSED', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26223, 11, '12g Aridos(Arenas-Gravas)', 'CLOSED', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26224, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26225, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26226, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26227, 11, '12g Aridos(Arenas-Gravas)', 'PRODUCER', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26228, 11, '12g Aridos(Arenas-Gravas)', 'CLOSED', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26229, 11, '12g Aridos(Arenas-Gravas)', 'CLOSED', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26230, 11, '12g Aridos(Arenas-Gravas)', 'CLOSED', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26231, 11, '12g Aridos(Arenas-Gravas)', 'CLOSED', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26232, 11, '12g Aridos(Arenas-Gravas)', 'CLOSED', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26233, 11, '12g Aridos(Arenas-Gravas)', 'CLOSED', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26234, 11, '12g Aridos(Arenas-Gravas)', 'CLOSED', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26235, 11, '12g Aridos(Arenas-Gravas)', 'CLOSED', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26236, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26237, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26238, 11, '12g Aridos(Arenas-Gravas)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26239, 35, '09b U-Cu en areniscas (U-V-Cu-Ag)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26240, 35, '09b U-Cu en areniscas (U-V-Cu-Ag)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26242, 116, '08f Volcanogénico (W)', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', NULL, 'diseminada (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Candiani, Juan Carlos; Ulacco, Huberto; Ojeda, Guillermo, 2016
Hoja Geológica 3366-II Villa de Merlo, provincias de San Luis y Córdoba. Instituto de Geología y Recursos Minerales, Servicio Geológico Minero Argentino
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 415

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26243, 116, '08f Volcanogénico (W)', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', NULL, NULL, NULL, NULL, NULL, NULL, 'Candiani, Juan Carlos; Ulacco, Huberto; Ojeda, Guillermo, 2016
Hoja Geológica 3366-II Villa de Merlo, provincias de San Luis y Córdoba. Instituto de Geología y Recursos Minerales, Servicio Geológico Minero Argentino
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 415

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26244, 116, '08f Volcanogénico (W)', 'CLOSED', 'UNKNOWN', 'Sierras Pampeanas', NULL, NULL, NULL, NULL, NULL, NULL, 'Candiani, Juan Carlos; Ulacco, Huberto; Ojeda, Guillermo, 2016
Hoja Geológica 3366-II Villa de Merlo, provincias de San Luis y Córdoba. Instituto de Geología y Recursos Minerales, Servicio Geológico Minero Argentino
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 415

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26245, 168, '03c Pegmatitas Simples(Feldespato-Qz-Mica)', 'UNKNOWN', 'UNKNOWN', 'Sierras Pampeanas', NULL, NULL, NULL, NULL, NULL, NULL, 'Furque, Guillermo; González, Pablo; Caballé, Marcelo; Pérez, Luis; Cardó, Raúl; Godeas, Marta; Conde, Alejandro; Pucci, Juan, 2003
Hoja Geológica 3169-II, San José de Jáchal. Provincias de San Juan y La Rioja. Instituto de Geología y Recursos Minerales, Servicio Geológico Minero Argentino.
Hoja Geológica a 1:250.000. Programa Nacional de Cartas Geológicas de la República Argentina. SEGEMAR., Volume 259

Zappettini, Eduardo; Segal, Susana; Godeas, Marta, 1999
Recursos Minerales de la República Argentina
Anales del Servicio Geológico Minero Argentino, Volume 35', NULL),
    (26246, 119, '07e Polimetálico complejo (Pb-Ag-Zn-Cu (±Au±Sb±Bi±W)', 'PAST_PRODUCER', 'SMALL', 'Cordillera Oriental', NULL, 'vetiforme (Zona de alteración proximal); brechiforme (zona de mineralización principal)', NULL, NULL, NULL, NULL, 'Peñaranda, Franco Elías, 2022
Geología y metalogénesis de las Minas Santa Ana, San Rafael y Abra de Minas, Cordillera Oriental, Provincia de Jujuy, Argentina.
Trabajo Final de grado. Universidad Nacional de Córdoba, Facultad de Ciencias Exactas Físicas y Naturales (FCEFyN) - 179', NULL),
    (26247, 119, '07e Polimetálico complejo (Pb-Ag-Zn-Cu (±Au±Sb±Bi±W)', 'CLOSED', 'UNKNOWN', 'Cordillera Oriental', NULL, 'vetifome (zona de mineralización principal)', NULL, NULL, 'Pb Cu Zn Ag', '(1) Fecha de actualización: Fm. Fundición', 'Chayle, Waldo, 1986
La presencia de Baritina en la localidad de Mudana (Depto. Tilcara) Pcia. de Jujuy.
Revista del Instituto de Geología y Minería., p. 176 - 183

Chomnales, R., 1971
Estudio microscópico de cortes pulidos procedentes de Mina Mudana. Informe inédito.
Instituto de Geología y Minería. Universidad Nacional de Tucumán., 1 p.

Rosco, J., 1971
Reconocimiento de la mina de plomo "La Mudana", departamento Tilcara, Provincia de Jujuy.
Dirección Provincial de Minería de Jujuy. , 9 p.', NULL),
    (26248, 48, '07h Termal (Travertino-Boratos)', 'OCCURRENCE', 'SMALL', 'Puna', NULL, 'bancos (zona de mineralización principal)', NULL, NULL, NULL, '(1) volcánica (andesita); Fecha de actualización: Complejo Volcánico Coranzulí; Serie magmática: calcoalcalino; Ambiente de emplazamiento deposicional: continentalLitologías individuales:andesita', 'Tuttolomondo, Fernando, 1970
Cantera de travertino Telar Cueva o Cueva del Tigre Dto. Susques Provincia de Jujuy
Dirección Provincial de Minería de Jujuy, 7 p., 1 maps.', NULL),
    (26249, 35, '09b U-Cu en areniscas (U-V-Cu-Ag)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (26250, NULL, '09k Caliza-Dolomía', 'UNKNOWN', 'UNKNOWN', 'Cordillera Oriental', NULL, 'bancos (zona mineralizada principal)', NULL, NULL, NULL, NULL, 'Ramos, María Constanza, 1964
Estudio geológico de la cantera San Francisco
Dirección General de Minas, 11 p., 3 maps.', NULL),
    (26251, NULL, '09k Caliza-Dolomía', 'PRODUCER', 'SMALL', 'Cordillera Oriental', 'continental (roca huésped)', 'bancos (zona mineralizada principal)', NULL, NULL, NULL, NULL, NULL, NULL),
    (26252, 35, '09b U-Cu en areniscas (U-V-Cu-Ag)', 'EXPLORATION', 'SMALL', 'Cordillera Oriental', NULL, 'lentes (zona mineralizada principal)', NULL, NULL, 'U', NULL, 'Romano, Hugo, 1999
Distrito Uranífero Tonco-Amblayo, Salta
Anales del Servicio Geológico Minero Argentino, Volume 35, p. 959 - 970', NULL),
    (26253, 35, '09b U-Cu en areniscas (U-V-Cu-Ag)', 'EXPLORATION', 'SMALL', 'Cordillera Oriental', NULL, 'lenticular y bancos (zona mineralizada principal)', NULL, NULL, 'U', NULL, 'Romano, Hugo, 1999
Distrito Uranífero Tonco-Amblayo, Salta
Anales del Servicio Geológico Minero Argentino, Volume 35, p. 959 - 970', NULL),
    (26254, 35, '09b U-Cu en areniscas (U-V-Cu-Ag)', 'OCCURRENCE', 'UNKNOWN', 'Cordillera Oriental', NULL, 'Niveles (zona mineralizada principal)', NULL, NULL, NULL, NULL, 'Romano, Hugo, 1999
Distrito Uranífero Tonco-Amblayo, Salta
Anales del Servicio Geológico Minero Argentino, Volume 35, p. 959 - 970', NULL),
    (26255, 35, '09b U-Cu en areniscas (U-V-Cu-Ag)', 'OCCURRENCE', 'OCCURRENCE', 'Cordillera Oriental', NULL, 'bancos', NULL, NULL, 'U', NULL, 'Romano, Hugo, 1999
Distrito Uranífero Tonco-Amblayo, Salta
Anales del Servicio Geológico Minero Argentino, Volume 35, p. 959 - 970', NULL),
    (26256, 35, '09b U-Cu en areniscas (U-V-Cu-Ag)', 'OCCURRENCE', 'OCCURRENCE', 'Cordillera Oriental', NULL, 'lenticular y bancos (zona mineralizada principal)', NULL, NULL, 'U', NULL, 'Romano, Hugo, 1999
Distrito Uranífero Tonco-Amblayo, Salta
Anales del Servicio Geológico Minero Argentino, Volume 35, p. 959 - 970', NULL),
    (26257, 35, '09b U-Cu en areniscas (U-V-Cu-Ag)', 'OCCURRENCE', 'OCCURRENCE', 'Cordillera Oriental', NULL, NULL, NULL, NULL, NULL, NULL, 'Romano, Hugo, 1999
Distrito Uranífero Tonco-Amblayo, Salta
Anales del Servicio Geológico Minero Argentino, Volume 35, p. 959 - 970', NULL),
    (26258, 35, '09b U-Cu en areniscas (U-V-Cu-Ag)', 'OCCURRENCE', 'OCCURRENCE', 'Cordillera Oriental', NULL, 'lentes y bancos (zona mineralizada principal)', NULL, NULL, 'U', NULL, 'Romano, Hugo, 1999
Distrito Uranífero Tonco-Amblayo, Salta
Anales del Servicio Geológico Minero Argentino, Volume 35, p. 959 - 970', NULL),
    (26259, 35, '09b U-Cu en areniscas (U-V-Cu-Ag)', 'OCCURRENCE', 'OCCURRENCE', 'Cordillera Oriental', NULL, 'lentes y bancos (zona mineralizada principal)', NULL, NULL, 'U', '(1)', 'Romano, Hugo, 1999
Distrito Uranífero Tonco-Amblayo, Salta
Anales del Servicio Geológico Minero Argentino, Volume 35, p. 959 - 970', NULL),
    (26260, 65, '07a Manganeso (Mn+-F)', 'OCCURRENCE', 'OCCURRENCE', 'Cordillera Oriental', NULL, 'vetiforme (zona mineralizada principal)', NULL, NULL, 'Mn', NULL, NULL, NULL),
    (26261, 35, '09b U-Cu en areniscas (U-V-Cu-Ag)', 'OCCURRENCE', 'OCCURRENCE', 'Cordillera Oriental', NULL, 'cemento (zona mineralizada principal)', NULL, NULL, 'U-Cu', NULL, 'Salado Paz, Natalia; Barrabino, Emilio; Quiroga, Mirta; Baigorria, M. Belén ; Katsini, Fedra Editor(s)), 2023
Estudio geológico y mineralógico preliminar del depósito Cajoncillo, yacimiento estratoligado U-Cu, Valle de Amblayo,provincia de Salta.
Serie D Publicación Especial N.º 16, Actas del 14° Congreso de Mineralogía, Petrología Ígnea y Metamórfica, y Metalogénesis, Asociación geológica argentina', NULL),
    (26262, 35, '09b U-Cu en areniscas (U-V-Cu-Ag)', 'OCCURRENCE', 'SMALL', 'Cordillera Oriental', NULL, 'impregnación (niveles arenosos)', NULL, NULL, 'U', NULL, 'Stipanicic, P.N.; Baulies, O.L.; Rodrigo, F.; Martínez, C.G:, 1960
Los depósitos uraníferos en rocas sedimentarias de la República Argentina.
Comisión Nacional de Energía Atómica, Departamento de materias primas.', NULL),
    (26263, 35, '09b U-Cu en areniscas (U-V-Cu-Ag)', 'EXPLORATION', 'SMALL', 'Cordillera Orienta', NULL, 'bancos (zona mineralizada principal)', NULL, NULL, 'U-Cu', NULL, 'Stipanicic, P.N.; Baulies, O.L.; Rodrigo, F.; Martínez, C.G:, 1960
Los depósitos uraníferos en rocas sedimentarias de la República Argentina.
Comisión Nacional de Energía Atómica, Departamento de materias primas.', NULL),
    (26264, 157, '04b Cu (±Mo±Au)', 'UNKNOWN', 'UNKNOWN', NULL, NULL, 'relleno de fracturas; diseminado', NULL, 'propilítica sericitica/argílica silicificación-potásica', NULL, NULL, 'Zolezzi, Roberto, 1975
Área de reserva N° 4 Quebrada Varita - Las Vacas. Plan La Rioja', NULL),
    (26265, NULL, '09k Caliza-Dolomía', 'PAST_PRODUCER', 'UNKNOWN', 'Sistema de Santa Bárbara', NULL, 'bancos (zona mineralizada principal)', NULL, NULL, NULL, NULL, 'Ramos, María C., 1967
Cantera La Quinta Dpto. Santa Bárbara - Jujuy
Informe Inédito, Dirección Provincial de Minería de Jujuy', NULL),
    (26266, 122, '07g Azufre Fumarólico (Azufre)', 'PAST_PRODUCER', 'SMALL', 'Sistema de Santa Bárbara', NULL, 'mantiforme (zona mineralizada principal)', NULL, NULL, NULL, NULL, 'Reverberi, Oscar, 1961
Azufrera Santa Bárbara Paraje La Quinta, Distrito El Palmar, Dpto Santa Bárbara, Provinica Jujuy
Informe Inédito, Dirección Nacional de Geología y Minería', NULL),
    (26267, 73, '09a Cu sedimentario (Cu-Ag)', 'OCCURRENCE', 'SMALL', 'Sistema de Santa Bárbara', NULL, 'lenticular y bancos (zona de mineralización principal)', NULL, NULL, 'Cu', NULL, 'Iza, Antenor; Onder, F, 1969
Reconocimiento Preliminar de Áreas Mineralizadas en el Opto. de Santa Bárbara
Informe Inédito, Dirección Provincial de Minería de Jujuy', NULL)
  ) AS v(depno, dt_id, dt_local, status, size_cat, prov, tect, mstyle, form, alt, meta, ign, refs, com)
  ON v.depno::text = nl.external_id;

INSERT INTO deposit_commodities (depositid, commodity_id, commodity_role, createdby)
SELECT d.depositid, v.cid, v.role, 'claude_sigam_20260910'
FROM (VALUES
    (239, 248, 'PRIMARY'),
    (239, 241, 'SECONDARY'),
    (239, 242, 'SECONDARY'),
    (240, 241, 'PRIMARY'),
    (240, 248, 'SECONDARY'),
    (243, 241, 'PRIMARY'),
    (243, 242, 'SECONDARY'),
    (243, 248, 'SECONDARY'),
    (243, 249, 'SECONDARY'),
    (264, 241, 'PRIMARY'),
    (264, 248, 'SECONDARY'),
    (264, 242, 'SECONDARY'),
    (264, 247, 'SECONDARY'),
    (264, 249, 'SECONDARY'),
    (268, 242, 'PRIMARY'),
    (268, 241, 'SECONDARY'),
    (268, 248, 'SECONDARY'),
    (270, 241, 'PRIMARY'),
    (270, 248, 'SECONDARY'),
    (270, 242, 'SECONDARY'),
    (271, 241, 'PRIMARY'),
    (271, 248, 'SECONDARY'),
    (271, 242, 'SECONDARY'),
    (272, 241, 'PRIMARY'),
    (272, 248, 'SECONDARY'),
    (272, 242, 'SECONDARY'),
    (273, 241, 'PRIMARY'),
    (273, 248, 'SECONDARY'),
    (273, 242, 'SECONDARY'),
    (287, 241, 'PRIMARY'),
    (287, 242, 'SECONDARY'),
    (287, 248, 'SECONDARY'),
    (510, 241, 'PRIMARY'),
    (510, 242, 'SECONDARY'),
    (2095, 245, 'PRIMARY'),
    (2199, 245, 'PRIMARY'),
    (4007, 236, 'PRIMARY'),
    (4007, 214, 'SECONDARY'),
    (5105, 236, 'PRIMARY'),
    (5105, 214, 'SECONDARY'),
    (5126, 236, 'PRIMARY'),
    (5136, 236, 'PRIMARY'),
    (5137, 236, 'PRIMARY'),
    (5138, 236, 'PRIMARY'),
    (5233, 241, 'SECONDARY'),
    (5233, 242, 'SECONDARY'),
    (11168, 170, 'PRIMARY'),
    (11175, 72, 'PRIMARY'),
    (11261, 174, 'PRIMARY'),
    (11358, 241, 'PRIMARY'),
    (11358, 248, 'SECONDARY'),
    (11358, 242, 'SECONDARY'),
    (24561, 235, 'PRIMARY'),
    (24561, 247, 'SECONDARY'),
    (24581, 249, 'PRIMARY'),
    (24581, 248, 'SECONDARY'),
    (24582, 249, 'PRIMARY'),
    (24582, 248, 'SECONDARY'),
    (24588, 235, 'PRIMARY'),
    (24604, 241, 'PRIMARY'),
    (24604, 242, 'SECONDARY'),
    (24604, 248, 'SECONDARY'),
    (24864, 143, 'PRIMARY'),
    (24868, 143, 'PRIMARY'),
    (24870, 143, 'PRIMARY'),
    (24871, 143, 'PRIMARY'),
    (24890, 139, 'PRIMARY'),
    (24891, 139, 'PRIMARY'),
    (24893, 139, 'PRIMARY'),
    (25016, 151, 'PRIMARY'),
    (25017, 151, 'PRIMARY'),
    (25478, 117, 'PRIMARY'),
    (25484, 167, 'PRIMARY'),
    (25497, 167, 'PRIMARY'),
    (25501, 167, 'PRIMARY'),
    (25621, 68, 'PRIMARY'),
    (25622, 68, 'PRIMARY'),
    (25623, 68, 'PRIMARY'),
    (25638, 68, 'PRIMARY'),
    (25641, 139, 'PRIMARY'),
    (25641, 123, 'SECONDARY'),
    (25643, 139, 'PRIMARY'),
    (25643, 123, 'SECONDARY'),
    (25651, 70, 'PRIMARY'),
    (25670, 151, 'PRIMARY'),
    (25698, 70, 'PRIMARY'),
    (25711, 70, 'PRIMARY'),
    (25715, 70, 'PRIMARY'),
    (25722, 73, 'PRIMARY'),
    (25766, 72, 'PRIMARY'),
    (26143, 239, 'PRIMARY'),
    (26143, 244, 'SECONDARY'),
    (26144, 249, 'PRIMARY'),
    (26145, 249, 'PRIMARY'),
    (26146, 249, 'PRIMARY'),
    (26147, 249, 'PRIMARY'),
    (26148, 249, 'PRIMARY'),
    (26149, 241, 'PRIMARY'),
    (26149, 239, 'SECONDARY'),
    (26150, 239, 'PRIMARY'),
    (26150, 244, 'SECONDARY'),
    (26151, 239, 'PRIMARY'),
    (26151, 244, 'SECONDARY'),
    (26152, 239, 'PRIMARY'),
    (26152, 244, 'SECONDARY'),
    (26153, 212, 'PRIMARY'),
    (26153, 241, 'SECONDARY'),
    (26154, 236, 'PRIMARY'),
    (26155, 73, 'PRIMARY'),
    (26156, 73, 'PRIMARY'),
    (26157, 73, 'PRIMARY'),
    (26158, 73, 'PRIMARY'),
    (26159, 73, 'PRIMARY'),
    (26160, 73, 'PRIMARY'),
    (26161, 73, 'PRIMARY'),
    (26162, 73, 'PRIMARY'),
    (26163, 73, 'PRIMARY'),
    (26164, 73, 'PRIMARY'),
    (26165, 73, 'PRIMARY'),
    (26166, 73, 'PRIMARY'),
    (26167, 73, 'PRIMARY'),
    (26168, 73, 'PRIMARY'),
    (26169, 73, 'PRIMARY'),
    (26170, 73, 'PRIMARY'),
    (26171, 73, 'PRIMARY'),
    (26172, 73, 'PRIMARY'),
    (26173, 73, 'PRIMARY'),
    (26174, 73, 'PRIMARY'),
    (26175, 73, 'PRIMARY'),
    (26176, 73, 'PRIMARY'),
    (26177, 73, 'PRIMARY'),
    (26178, 73, 'PRIMARY'),
    (26179, 73, 'PRIMARY'),
    (26180, 73, 'PRIMARY'),
    (26181, 73, 'PRIMARY'),
    (26182, 73, 'PRIMARY'),
    (26183, 73, 'PRIMARY'),
    (26184, 73, 'PRIMARY'),
    (26185, 73, 'PRIMARY'),
    (26186, 73, 'PRIMARY'),
    (26187, 73, 'PRIMARY'),
    (26188, 73, 'PRIMARY'),
    (26189, 73, 'PRIMARY'),
    (26190, 73, 'PRIMARY'),
    (26191, 73, 'PRIMARY'),
    (26192, 73, 'PRIMARY'),
    (26193, 68, 'PRIMARY'),
    (26194, 68, 'PRIMARY'),
    (26195, 68, 'PRIMARY'),
    (26196, 68, 'PRIMARY'),
    (26197, 68, 'PRIMARY'),
    (26198, 68, 'PRIMARY'),
    (26199, 68, 'PRIMARY'),
    (26200, 68, 'PRIMARY'),
    (26201, 68, 'PRIMARY'),
    (26202, 68, 'PRIMARY'),
    (26203, 68, 'PRIMARY'),
    (26204, 68, 'PRIMARY'),
    (26205, 68, 'PRIMARY'),
    (26206, 68, 'PRIMARY'),
    (26207, 68, 'PRIMARY'),
    (26208, 68, 'PRIMARY'),
    (26209, 68, 'PRIMARY'),
    (26210, 68, 'PRIMARY'),
    (26211, 68, 'PRIMARY'),
    (26212, 68, 'PRIMARY'),
    (26213, 68, 'PRIMARY'),
    (26214, 68, 'PRIMARY'),
    (26215, 68, 'PRIMARY'),
    (26216, 68, 'PRIMARY'),
    (26217, 68, 'PRIMARY'),
    (26218, 68, 'PRIMARY'),
    (26219, 68, 'PRIMARY'),
    (26220, 68, 'PRIMARY'),
    (26221, 68, 'PRIMARY'),
    (26222, 68, 'PRIMARY'),
    (26223, 68, 'PRIMARY'),
    (26224, 68, 'PRIMARY'),
    (26225, 68, 'PRIMARY'),
    (26226, 68, 'PRIMARY'),
    (26227, 68, 'PRIMARY'),
    (26228, 68, 'PRIMARY'),
    (26229, 68, 'PRIMARY'),
    (26230, 68, 'PRIMARY'),
    (26231, 68, 'PRIMARY'),
    (26232, 68, 'PRIMARY'),
    (26233, 68, 'PRIMARY'),
    (26234, 68, 'PRIMARY'),
    (26235, 68, 'PRIMARY'),
    (26236, 68, 'PRIMARY'),
    (26237, 68, 'PRIMARY'),
    (26238, 68, 'PRIMARY'),
    (26239, 239, 'PRIMARY'),
    (26240, 239, 'PRIMARY'),
    (26242, 236, 'PRIMARY'),
    (26242, 249, 'SECONDARY'),
    (26243, 236, 'PRIMARY'),
    (26244, 236, 'PRIMARY'),
    (26245, 123, 'PRIMARY'),
    (26245, 139, 'SECONDARY'),
    (26245, 134, 'SECONDARY'),
    (26246, 241, 'PRIMARY'),
    (26246, 239, 'SECONDARY'),
    (26246, 248, 'SECONDARY'),
    (26246, 212, 'SECONDARY'),
    (26247, 212, 'PRIMARY'),
    (26247, 241, 'SECONDARY'),
    (26247, 239, 'SECONDARY'),
    (26247, 248, 'SECONDARY'),
    (26247, 242, 'SECONDARY'),
    (26248, 72, 'PRIMARY'),
    (26249, 239, 'PRIMARY'),
    (26250, 72, 'PRIMARY'),
    (26251, 72, 'PRIMARY'),
    (26252, 235, 'PRIMARY'),
    (26253, 235, 'PRIMARY'),
    (26254, 235, 'PRIMARY'),
    (26255, 235, 'PRIMARY'),
    (26256, 235, 'PRIMARY'),
    (26257, 235, 'PRIMARY'),
    (26258, 235, 'PRIMARY'),
    (26259, 235, 'PRIMARY'),
    (26260, 245, 'PRIMARY'),
    (26261, 235, 'PRIMARY'),
    (26261, 239, 'SECONDARY'),
    (26262, 235, 'PRIMARY'),
    (26263, 235, 'PRIMARY'),
    (26263, 239, 'SECONDARY'),
    (26264, 239, 'PRIMARY'),
    (26264, 224, 'SECONDARY'),
    (26265, 72, 'PRIMARY'),
    (26266, 286, 'PRIMARY'),
    (26267, 239, 'PRIMARY')
  ) AS v(depno, cid, role)
JOIN locations l ON l.external_id = v.depno::text AND l.locationtype='DEPOSIT' AND l.createdby='claude_sigam_20260910'
JOIN deposits d ON d.locationid = l.locationid;

INSERT INTO deposit_mineralogy (depositid, mineral_name_local, mineral_zone, mineral_id, createdby)
SELECT d.depositid, v.nm, v.zona, v.mid, 'claude_sigam_20260910'
FROM (VALUES
    (239, 'galena', 'irregular', 1961),
    (240, 'galena', 'vetiforme', 1961),
    (240, 'calcopirita', 'vetiforme', NULL),
    (240, 'pirita', 'vetiforme', NULL),
    (243, 'plata nativa', 'diseminada', NULL),
    (243, 'galena', 'mineralización vetiforme', 1961),
    (243, 'esfalerita', 'mineralización vetiforme', NULL),
    (243, 'argentita', 'mineralización vetiforme', NULL),
    (243, 'arsenopirita', 'mineralización vetiforme', NULL),
    (243, 'tetraedrita', 'mineralización vetiforme', NULL),
    (264, 'cerusita', 'irregular', NULL),
    (264, 'tetraedrita', 'irregular', NULL),
    (264, 'stannoidita', 'irregular', NULL),
    (264, 'galena', 'venillas', 1961),
    (264, 'esfalerita', 'venillas', NULL),
    (264, 'acantita', 'venillas', NULL),
    (268, 'esfalerita', 'diseminada', NULL),
    (268, 'proustita', 'diseminada', NULL),
    (268, 'galena', 'diseminada', 1961),
    (268, 'jamesonita', 'diseminada', NULL),
    (268, 'cerusita-anglesita', 'irregular', NULL),
    (270, 'pirita', 'diseminada', NULL),
    (270, 'cerusita', 'irregular', NULL),
    (270, 'galena', 'venillas', 1961),
    (270, 'esfalerita', 'venillas', NULL),
    (271, 'arsenopirita', 'diseminada', NULL),
    (271, 'pirita', 'diseminada', NULL),
    (271, 'acantita', 'diseminada', NULL),
    (271, 'stannoidita', 'diseminada', NULL),
    (271, 'kesterita', 'diseminada', NULL),
    (271, 'galena', 'venillas', 1961),
    (271, 'esfalerita', 'venillas', NULL),
    (272, 'galena', 'diseminada', 1961),
    (272, 'esfalerita', 'diseminada', NULL),
    (272, 'pirargirita', 'diseminada', NULL),
    (272, 'pirita', 'diseminada', NULL),
    (272, 'cerusita', 'irregular', NULL),
    (273, 'galena', 'diseminada', 1961),
    (273, 'esfalerita', 'diseminada', NULL),
    (273, 'vanadinita', 'irregular', NULL),
    (273, 'cerusita', 'irregular', NULL),
    (287, 'galena', 'diseminada', 1961),
    (287, 'esfalerita', 'diseminada', NULL),
    (287, 'acantita', 'diseminada', NULL),
    (287, 'stannita', 'diseminada', NULL),
    (287, 'calcopirita', 'diseminada', NULL),
    (510, 'pirita', 'venas y diseminado', NULL),
    (2095, 'goethita', 'mineral de oxidación', NULL),
    (2095, 'psilomelano', 'mineral primario', NULL),
    (2095, 'criptomelano', 'mineral primario', NULL),
    (2095, 'calcedonia', 'mineral primario', NULL),
    (2095, 'ópalo', 'mineral primario', NULL),
    (2095, 'baritina', 'mineral primario', NULL),
    (2095, 'calcita', 'mineral primario', NULL),
    (2199, 'psilomelano', 'mineral primario', NULL),
    (2199, 'criptomelano', 'mineral primario', NULL),
    (2199, 'pirolusita', 'mineral primario', NULL),
    (2199, 'litioforita', 'mineral primario', NULL),
    (2199, 'nsutita', 'mineral primario', NULL),
    (4007, 'limonitas', 'minerales de oxidación', NULL),
    (4007, 'malaquita', 'minerales de oxidación', NULL),
    (4007, 'wolframita', 'mineralización primaria', NULL),
    (4007, 'bismutinita', 'mineralización primaria', NULL),
    (4007, 'scheelita', 'mineralización primaria', NULL),
    (4007, 'calcopirita', 'mineralización primaria', NULL),
    (4007, 'molibdenita', 'mineralización primaria', NULL),
    (4007, 'pirita', 'mineralización primaria', NULL),
    (4007, 'covellina', 'mineralización secundaria', NULL),
    (4007, 'digenita', 'mineralización secundaria', NULL),
    (5105, 'fluorita', '/ zona mineralizada principal', NULL),
    (5105, 'tungstita', '/ zona mineralizada principal', NULL),
    (5105, 'minerales de Bi', '/ zona mineralizada principal', NULL),
    (5105, 'scheelita', 'diseminada / zona mineralizada principal', NULL),
    (5126, 'scheelita', 'diseminada, vetiforme / zona mineralizada principal', NULL),
    (5126, 'esfalerita', 'diseminada, vetiforme / zona mineralizada principal', NULL),
    (5126, 'pirita', 'diseminada, vetiforme / zona mineralizada principal', NULL),
    (5126, 'bismutina', 'diseminada, vetiforme / zona mineralizada principal', NULL),
    (5233, 'wolframita', 'diseminada / zona mineralizada principal', NULL),
    (11168, 'montmorillonita', 'alteración', NULL),
    (11175, 'carbonato', 'bancos', NULL),
    (11261, 'gibbsita', 'horizontes', NULL),
    (11261, 'selenita', 'horizontes', NULL),
    (11358, 'pirita', 'mineralización vetiforme', NULL),
    (11358, 'arsenopirita', 'mineralización vetiforme', NULL),
    (11358, 'esfalerita', 'mineralización vetiforme', NULL),
    (11358, 'oro nativo', 'mineralización vetiforme', NULL),
    (11358, 'galena', 'mineralización vetiforme', 1961),
    (11358, 'tetraedrita', 'mineralización vetiforme', NULL),
    (24561, 'carnotita', 'bolsones y diseminada', NULL),
    (24561, 'coffinita', 'bolsones y diseminada', NULL),
    (24561, 'tyuyamunita', 'bolsones y diseminada', NULL),
    (24581, 'galena', 'vetas y vetillas', 1961),
    (24581, 'pirita', 'vetas y vetillas', NULL),
    (24581, 'electrum', 'vetas y vetillas', NULL),
    (24582, 'galena', 'vetas y vetillas', 1961),
    (24582, 'pirita', 'vetas y vetillas', NULL),
    (24588, 'carnotita', 'horizontes', NULL),
    (24604, 'cerusita', 'supergénica', NULL),
    (24604, 'crisocola', 'supergénica', NULL),
    (24604, 'turquesa', 'supergénica', NULL),
    (24604, 'galena', 'vetas y vetillas', 1961),
    (25016, 'vermiculita', 'alteración', NULL),
    (25017, 'vermiculita', 'alteración', NULL),
    (25484, 'caolinita', 'alteración', NULL),
    (26143, 'malaquita', '/ mineralización secundaria', NULL),
    (26143, 'cuarzo', '/ ganga', NULL),
    (26143, 'bornita', 'diseminada / zona de mineralización principal', NULL),
    (26143, 'magnetita', 'masiva / zona de mineralización principal', NULL),
    (26143, 'calcosina', 'vetillas / mineralización secundaria', NULL),
    (26143, 'covelina', 'vetillas / mineralización secundaria', NULL),
    (26144, 'oro', 'aluvial', NULL),
    (26145, 'oro', 'placer', NULL),
    (26146, 'oro', 'placer', NULL),
    (26147, 'oro', 'placer', NULL),
    (26148, 'oro', 'placer', NULL),
    (26149, 'galena', 'vetas', 1961),
    (26149, 'calcopirita', 'vetas', NULL),
    (26149, 'calcosina', 'vetas', NULL),
    (26149, 'bornita', 'vetas', NULL),
    (26149, 'cuarzo', 'vetas', NULL),
    (26149, 'calcita', 'vetas', NULL),
    (26149, 'malaquita', 'vetas', NULL),
    (26149, 'azurita', 'vetas', NULL),
    (26149, 'goethita', 'vetas', NULL),
    (26150, 'anatasa', '/ mineralización secundaria', NULL),
    (26150, 'calcosina', '/ mineralización secundaria', NULL),
    (26150, 'cuarzo', '/ ganga', NULL),
    (26150, 'granate', '/ ganga', NULL),
    (26150, 'apatito', '/ ganga', NULL),
    (26150, 'zircón', '/ ganga', NULL),
    (26150, 'biotita', '/ ganga', NULL),
    (26150, 'epidoto', '/ ganga', NULL),
    (26150, 'clorita', '/ ganga', NULL),
    (26150, 'albita', '/ ganga', NULL),
    (26150, 'calcopirita', 'diseminada / zona de mineralización principal', NULL),
    (26150, 'bornita', 'diseminada / zona de mineralización principal', NULL),
    (26150, 'ilmenita', 'diseminada / zona de mineralización principal', NULL),
    (26150, 'magnetita', 'masiva, diseminada / zona de mineralización principal', NULL),
    (26150, 'pirita', 'vetas, diseminada / zona de mineralización principal', NULL),
    (26150, 'limonita', 'vetillas / mineralización secundaria', NULL),
    (26150, 'hematita', 'vetillas / mineralización secundaria', NULL),
    (26150, 'carbonato de cobre', 'vetillas / secundario', NULL),
    (26151, 'magnetita', '/ zona de mineralización principal', NULL),
    (26151, 'ilmenita', '/ zona de mineralización principal', NULL),
    (26151, 'bornita', '/ zona de mineralización principal', NULL),
    (26151, 'digenita', '/ zona de mineralización secundaria', NULL),
    (26151, 'covelina', '/ zona de mineralización secundaria', NULL),
    (26151, 'calcosina', '/ zona de mineralización secundaria', NULL),
    (26151, 'malaquita', '/ zona de mineralización secundaria', NULL),
    (26151, 'limonita', '/ zona de mineralización secundaria', NULL),
    (26151, 'cuarzo', '/ ganga', NULL),
    (26151, 'arcillas', '/ ganga', NULL),
    (26151, 'zeolitas', '/ ganga', NULL),
    (26152, 'magnetita', '/ zona de mineralización principal', NULL),
    (26152, 'hematita', '/ zona de mineralización principal', NULL),
    (26152, 'ilmenita', '/ zona de mineralización principal', NULL),
    (26152, 'calcopirita', '/ zona de mineralización principal', NULL),
    (26152, 'pirita', '/ zona de mineralización principal', NULL),
    (26152, 'calcosina', '/ zona de mineralización secundaria', NULL),
    (26152, 'covelina', '/ zona de mineralización secundaria', NULL),
    (26152, 'malaquita', '/ zona de mineralización secundaria', NULL),
    (26152, 'crisocola', '/ zona de mineralización secundaria', NULL),
    (26152, 'cobre nativo', '/ zona de mineralización secundaria', NULL),
    (26152, 'cuprita', '/ zona de mineralización secundaria', NULL),
    (26152, 'cuarzo', '/ ganga', NULL),
    (26152, 'biotita', '/ ganga', NULL),
    (26152, 'epidoto', '/ ganga', NULL),
    (26152, 'albita', '/ ganga', NULL),
    (26152, 'clorita', '/ ganga', NULL),
    (26152, 'arcillas', '/ ganga', NULL),
    (26153, 'cuarzo', 'brecha', NULL),
    (26153, 'malaquita', 'patinas', NULL),
    (26153, 'baritina', 'vetas', NULL),
    (26153, 'galena-', 'vetas', NULL),
    (26154, 'scheelita', 'diseminada / zona de mineralización principal', NULL),
    (26155, 'olivino', '/ accesorio', NULL),
    (26155, 'diópsido', '/ accesorio', NULL),
    (26155, 'serpetina', '/ accesorio', NULL),
    (26155, 'antigorita', '/ accesorio', NULL),
    (26155, 'crisotilo', '/ accesorio', NULL),
    (26155, 'calcita', 'bancos / zona de mineralización principal', NULL),
    (26155, 'dolomita', 'bancos / zona de mineralización principal', NULL),
    (26156, 'serpentina', '/ accesorio', NULL),
    (26156, 'dolomita', 'bancos / zona de mineralización principal', NULL),
    (26156, 'calcita', 'bancos / zona de mineralización principal', NULL),
    (26157, 'cuarzo', '/ accesorio', NULL),
    (26157, 'epidoto', '/ accesorio', NULL),
    (26157, 'granate', '/ accesorio', NULL),
    (26157, 'wollastonita', '/ accesorio', NULL),
    (26157, 'dolomita', 'bancos / zona de mineralización principal', NULL),
    (26157, 'calcita', 'bancos / zona de mineralización principal', NULL),
    (26158, 'cuarzo', '/ accesorio', NULL),
    (26158, 'grafito', '/ accesorio', NULL),
    (26158, 'anfibol', '/ accesorio', NULL),
    (26158, 'flogopita', '/ accesorio', NULL),
    (26158, 'dolomita', 'bancos / zona de mineralización principal', NULL),
    (26158, 'calcita', 'bancos / zona de mineralización principal', NULL),
    (26159, 'calcita', '/ zona de mineralización principal', NULL),
    (26159, 'dolomita', '/ zona de mineralización principal', NULL),
    (26160, 'dolomita', '/ zona de mineralización principal', NULL),
    (26160, 'calcita', 'bancos / zona de mineralización principal', NULL),
    (26161, 'calcita', '/ zona de mineralización principal', NULL),
    (26161, 'dolomita', '/ zona de mineralización principal', NULL),
    (26162, 'calcita', '/ zona de mineralización principal', NULL),
    (26162, 'dolomita', '/ zona de mineralización principal', NULL),
    (26163, 'calcita', '/ zona de mineralización principal', NULL),
    (26163, 'dolomita', '/ zona de mineralización principal', NULL),
    (26164, 'calcita', '/ zona de mineralización principal', NULL),
    (26164, 'dolomita', '/ zona de mineralización principal', NULL),
    (26165, 'calcita', '/ zona de mineralización principal', NULL),
    (26165, 'dolomita', '/ zona de mineralización principal', NULL),
    (26166, 'calcita', '/ zona de mineralización principal', NULL),
    (26166, 'dolomita', '/ zona de mineralización principal', NULL),
    (26167, 'calcita', '/ zona de mineralización principal', NULL),
    (26167, 'dolomita', '/ zona de mineralización principal', NULL),
    (26169, 'diópsido', '/ accesorio', NULL),
    (26169, 'wollastonita', '/ accesorio', NULL),
    (26169, 'calcita', 'mantos / zona de mineralización principal', NULL),
    (26169, 'dolomita', 'mantos / zona de mineralización principal', NULL),
    (26170, 'cuarzo', '/ accesorio', NULL),
    (26170, 'wollastonita', '/ accesorio', NULL),
    (26170, 'tremolita', '/ accesorio', NULL),
    (26170, 'flogopita', '/ accesorio', NULL),
    (26170, 'calcita', 'bancos / zona de mineralización principal', NULL),
    (26171, 'dolomita', '/ zona de mineralización principal', NULL),
    (26171, 'calcita', '/ zona de mineralización principal', NULL),
    (26172, 'calcita', '/ zona de mineralización principal', NULL),
    (26172, 'serpentina', '/ accesorio', NULL),
    (26172, 'cuarzo', '/ accesorio', NULL),
    (26172, 'wollastonita', '/ accesorio', NULL),
    (26172, 'flogopita', '/ accesorio', NULL),
    (26172, 'tremolita', '/ accesorio', NULL),
    (26172, 'grafito', '/ accesorio', NULL),
    (26173, 'calcita', '/ zona de mineralización principal', NULL),
    (26173, 'serpentina', '/ zona de mineralización principal', NULL),
    (26173, 'cuarzo', '/ zona de mineralización principal', NULL),
    (26173, 'wollastonita', '/ accesorio', NULL),
    (26173, 'grafito', '/ accesorio', NULL),
    (26173, 'flogopita', '/ accesorio', NULL),
    (26173, 'tremolita', '/ accesorio', NULL),
    (26174, 'calcita', '/ zona de mineralización principal', NULL),
    (26174, 'serpentina', '/ accesorio', NULL),
    (26174, 'cuarzo', '/ accesorio', NULL),
    (26174, 'wollastonita', '/ accesorio', NULL),
    (26174, 'grafito', '/ accesorio', NULL),
    (26174, 'flogopita', '/ accesorio', NULL),
    (26174, 'tremolita', '/ accesorio', NULL),
    (26175, 'calcita', '/ zona de mineralización principal', NULL),
    (26175, 'serpentina', '/ accesorio', NULL),
    (26175, 'cuarzo', '/ accesorio', NULL),
    (26175, 'wollastonita', '/ accesorio', NULL),
    (26175, 'grafito', '/ accesorio', NULL),
    (26175, 'flogopita', '/ accesorio', NULL),
    (26175, 'tremolita', '/ accesorio', NULL),
    (26176, 'calcita', '/ zona de mineralización principal', NULL),
    (26176, 'dolomita', '/ zona de mineralización principal', NULL),
    (26176, 'serpentina', '/ accesorio', NULL),
    (26176, 'anfibol', '/ accesorio', NULL),
    (26176, 'olivino', '/ accesorio', NULL),
    (26176, 'flogopita', '/ accesorio', NULL),
    (26177, 'calcita', '/ zona de mineralización principal', NULL),
    (26177, 'dolomita', '/ zona de mineralización principal', NULL),
    (26177, 'serpentina', '/ accesorio', NULL),
    (26177, 'anfibol', '/ accesorio', NULL),
    (26177, 'olivino', '/ accesorio', NULL),
    (26177, 'flogopita', '/ accesorio', NULL),
    (26178, 'calcita', '/ zona de mineralización principal', NULL),
    (26178, 'dolomita', '/ zona de mineralización principal', NULL),
    (26178, 'serpetina', '/ accesorio', NULL),
    (26178, 'anfibol', '/ accesorio', NULL),
    (26178, 'olivino', '/ accesorio', NULL),
    (26178, 'flogopita', '/ accesorio', NULL),
    (26179, 'dolomita', '/ zona de mineralización principal', NULL),
    (26179, 'calcita', '/ zona de mineralización principal', NULL),
    (26179, 'serpentina', '/ accesorio', NULL),
    (26179, 'anfibol', '/ accesorio', NULL),
    (26179, 'olivino', '/ accesorio', NULL),
    (26179, 'flogopita', '/ accesorio', NULL),
    (26180, 'dolomita', '/ zona de mineralización principal', NULL),
    (26180, 'calcita', '/ zona de mineralización principal', NULL),
    (26180, 'serpentina', '/ accesorio', NULL),
    (26180, 'anfibol', '/ accesorio', NULL),
    (26180, 'olivino', '/ accesorio', NULL),
    (26180, 'flogopita', '/ accesorio', NULL),
    (26181, 'calcita', '/ zona de mineralización principal', NULL),
    (26181, 'dolomita', '/ zona de mineralización principal', NULL),
    (26181, 'serpetina', '/ accesorio', NULL),
    (26181, 'anfibol', '/ accesorio', NULL),
    (26181, 'olivino', '/ accesorio', NULL),
    (26181, 'flogopita', '/ accesorio', NULL),
    (26182, 'calcita', '/ zona de mineralización principal', NULL),
    (26182, 'dolomita', '/ zona de mineralización principal', NULL),
    (26182, 'serpentina', '/ accesorio', NULL),
    (26182, 'anfibol', '/ accesorio', NULL),
    (26182, 'olivino', '/ accesorio', NULL),
    (26182, 'flogopita', '/ accesorio', NULL),
    (26183, 'calcita', '/ zona de mineralización principal', NULL),
    (26183, 'dolomita', '/ zona de mineralización principal', NULL),
    (26183, 'serpentina', '/ accesorio', NULL),
    (26183, 'anfibol', '/ accesorio', NULL),
    (26183, 'olivino', '/ accesorio', NULL),
    (26183, 'flogopita', '/ accesorio', NULL),
    (26184, 'dolomita', '/ zona de mineralización principal', NULL),
    (26184, 'calcita', '/ zona de mineralización principal', NULL),
    (26184, 'serpentina', '/ accesorio', NULL),
    (26184, 'grafito', '/ accesorio', NULL),
    (26184, 'wollastonita', '/ accesorio', NULL),
    (26184, 'tremolita', '/ accesorio', NULL),
    (26184, 'granate', '/ accesorio', NULL),
    (26184, 'epidoto', '/ accesorio', NULL),
    (26185, 'dolomita', '/ zona de mineralización principal', NULL),
    (26185, 'calcita', '/ zona de mineralización principal', NULL),
    (26185, 'serpentina', '/ accesorio', NULL),
    (26185, 'grafito', '/ accesorio', NULL),
    (26185, 'wollastonita', '/ accesorio', NULL),
    (26185, 'tremolita', '/ accesorio', NULL),
    (26185, 'granate', '/ accesorio', NULL),
    (26185, 'epidoto', '/ accesorio', NULL),
    (26186, 'dolomita', '/ zona de mineralización principal', NULL),
    (26186, 'calcita', '/ zona de mineralización principal', NULL),
    (26186, 'serpentina', '/ accesorio', NULL),
    (26186, 'grafito', '/ accesorio', NULL),
    (26186, 'wollastonita', '/ accesorio', NULL),
    (26186, 'tremolita', '/ accesorio', NULL),
    (26186, 'granate', '/ accesorio', NULL),
    (26186, 'epidoto', '/ accesorio', NULL),
    (26187, 'calcita', '/ zona de mineralización principal', NULL),
    (26187, 'serpentina', '/ accesorio', NULL),
    (26187, 'diópsido', '/ accesorio', NULL),
    (26187, 'grafito', '/ accesorio', NULL),
    (26187, 'flogopita', '/ accesorio', NULL),
    (26188, 'calcita', '/ zona de mineralización principal', NULL),
    (26188, 'diópsido', '/ accesorio', NULL),
    (26188, 'olivino', '/ accesorio', NULL),
    (26188, 'dolomita', 'manto / zona de mineralización principal', NULL),
    (26189, 'dolomita', '/ zona de mineralización principal', NULL),
    (26189, 'calcita', '/ zona de mineralización principal', NULL),
    (26190, 'calcita', '/ zona de mineralización principal', NULL),
    (26190, 'serpentina', '/ accesorio', NULL),
    (26190, 'hornblenda', '/ accesorio', NULL),
    (26190, 'tremolita', '/ accesorio', NULL),
    (26190, 'olivino', '/ accesorio', NULL),
    (26190, 'bornita', '/ accesorio', NULL),
    (26190, 'malaquita', '/ accesorio', NULL),
    (26190, 'dolomita', 'bancos / zona de mineralización principal', NULL),
    (26191, 'dolomita', 'bancos / zona de mineralización principal', NULL),
    (26191, 'calcita', 'bancos / zona de mineralización principal', NULL),
    (26192, 'serpentina', '/ accesorio', NULL),
    (26192, 'olivino', '/ accesorio', NULL),
    (26192, 'hornblenda', '/ accesorio', NULL),
    (26192, 'diópsido', '/ accesorio', NULL),
    (26192, 'grafito', '/ accesorio', NULL),
    (26192, 'tremolita', '/ accesorio', NULL),
    (26192, 'wollastonita', '/ accesorio', NULL),
    (26192, 'dolomita', 'bancos / zona de mineralización principal', NULL),
    (26192, 'calcita', 'bancos / zona de mineralización principal', NULL),
    (26239, 'crisocola', 'mineralización estratoligada', NULL),
    (26239, 'malaquita-azurita', 'mineralización estratoligada', NULL),
    (26240, 'malaquita-azurita', 'mineralización estratoligada', NULL),
    (26240, 'crisocola', 'mineralización estratoligada', NULL),
    (26240, 'calcosina', 'mineralización estratoligada', NULL),
    (26240, 'uraninita', 'mineralización estratoligada', NULL),
    (26240, 'bitumen', 'mineralización estratoligada', NULL),
    (26242, 'limonita', '/ secundario', NULL),
    (26242, 'scheelita', 'diseminada / zona de mineralización principal', NULL),
    (26242, 'oro', 'diseminada / zona de mineralización principal', NULL),
    (26242, 'antimonita', 'diseminada / zona de mineralización principal', NULL),
    (26243, 'pirita', '/ secundario', NULL),
    (26243, 'scheelita', 'diseminada, venillas / zona de mineralización principal', NULL),
    (26244, 'pirita', '/ secundario', NULL),
    (26244, 'scheelita', 'diseminada, venillas / zona de mineralización principal', NULL),
    (26245, 'cuarzo', '/ mineral primario', NULL),
    (26245, 'plagioclasa', '/ mineral primario', NULL),
    (26245, 'biotita', '/ mineral primario', NULL),
    (26245, 'muscovita', '/ mineral primario', NULL),
    (26245, 'granate', '/ accesorio', NULL),
    (26245, 'microclino', '/ mineral primario', NULL),
    (26246, 'goethita', 'pátinas / mineral de oxidación', NULL),
    (26246, 'piromorfita', 'pátinas / mineral de oxidación', NULL),
    (26246, 'malaquita', 'pátinas / mineral de oxidación', NULL),
    (26246, 'azurita', 'pátinas / mineral de oxidación', NULL),
    (26246, 'óxidos de manganeso', 'pátinas / mineral de oxidación', NULL),
    (26246, 'calcosina', 'vetas / zona de mineralización principal', NULL),
    (26246, 'galena', 'vetas / zona de mineralización principal', 1961),
    (26246, 'bornita', 'vetas / zona de mineralización principal', NULL),
    (26246, 'calcopirita', 'vetas / zona de mineralización principal', NULL),
    (26246, 'pirita', 'vetas / zona de mineralización principal', NULL),
    (26246, 'tetraedrita-tennantita', 'vetas / zona de mineralización principal', NULL),
    (26246, 'cuarzo', 'vetas / ganga', NULL),
    (26246, 'baritina', 'vetas / ganga', NULL),
    (26247, 'baritina', 'vetas', NULL),
    (26247, 'galena', 'vetas', 1961),
    (26247, 'calcosina', 'vetas', NULL),
    (26247, 'Oro', 'vetas', NULL),
    (26247, 'pirargirita-proustita', 'vetas', NULL),
    (26247, 'berzelianita', 'vetas', NULL),
    (26247, 'óxidos de manganeso', 'vetas', NULL),
    (26247, 'malaquita', 'vetas', NULL),
    (26247, 'azurita', 'vetas', NULL),
    (26247, 'goethita', 'vetas', NULL),
    (26247, 'hematita', 'vetas', NULL),
    (26248, 'aragonita', 'bancos', NULL),
    (26249, 'malaquita', 'mineralización estratoligada', NULL),
    (26249, 'calcosina', 'mineralización estratoligada', NULL),
    (26249, 'bitumen', 'mineralización estratoligada', NULL),
    (26250, 'calcita', 'bancos', NULL),
    (26251, 'calcita', 'bancos', NULL),
    (26252, 'autunita', 'lenticular', NULL),
    (26252, 'meta-autunita', 'lenticular', NULL),
    (26252, 'carnotita', 'lenticular', NULL),
    (26252, 'tyuyamunita', 'lenticular', NULL),
    (26253, 'tyuyamunita', 'lenticular', NULL),
    (26253, 'autunita', 'lenticular', NULL),
    (26253, 'meta-autunita', 'lenticular', NULL),
    (26253, 'fosfuranilita', 'lenticular', NULL),
    (26260, 'pirolusita', 'vetas', NULL),
    (26260, 'calcita', 'vetas', NULL),
    (26261, 'crisocola', 'cemento', NULL),
    (26261, 'tenorita', 'cemento', NULL),
    (26261, 'cuprosklowskita', 'cemento', NULL),
    (26261, 'carnotita', 'cemento', NULL),
    (26261, 'cuprita', 'nódulos', NULL),
    (26261, 'pechblenda', 'nódulos', NULL),
    (26261, 'coffinita', 'nódulos', NULL),
    (26261, 'uranofano', 'nódulos', NULL),
    (26261, 'thorbernita', 'nódulos', NULL),
    (26261, 'uvanita', 'nódulos', NULL),
    (26262, 'meta-autunita', 'impregnaciones', NULL),
    (26262, 'metatorbernita', 'impregnaciones', NULL),
    (26262, 'fosfuranilita', 'impregnaciones', NULL),
    (26264, 'calcopirita', '/ mineral primario', NULL),
    (26264, 'bornita', '/ mineral primario', NULL),
    (26264, 'pirrotina', '/ mineral primario', NULL),
    (26264, 'molibdenita', '/ mineralización primaria', NULL),
    (26264, 'óxidos de Cu', '/ mineralización secundaria', NULL),
    (26264, 'limonitas', '/ mineralización secundaria', NULL),
    (26264, 'cuarzo', 'ganga', NULL),
    (26264, 'calcita', 'ganga', NULL),
    (26264, 'limonitas', 'ganga', NULL),
    (26264, 'covelina', 'mineralización secundaria', NULL),
    (26264, 'neodigenita', 'mineralización secundaria', NULL),
    (26264, 'pirita', 'relleno de fracturas / mineral primario', NULL),
    (26264, 'arsenopirita', 'relleno de fracturas / mineral primario', NULL),
    (26265, 'calcita', 'bancos', NULL),
    (26266, 'halita', 'eflorescencias', NULL),
    (26266, 'azufre', 'mantos', NULL),
    (26266, 'yeso', 'masiva', NULL),
    (26267, 'calcita', 'ganga', NULL),
    (26267, 'cuarzo', 'ganga', NULL),
    (26267, 'hematita', 'ganga', NULL),
    (26267, 'malaquita', 'impregnaciones', NULL),
    (26267, 'limonita', 'lenticular', NULL),
    (26267, 'covellina', 'venillas', NULL),
    (26267, 'calcosina', 'venillas', NULL)
  ) AS v(depno, nm, zona, mid)
JOIN locations l ON l.external_id = v.depno::text AND l.locationtype='DEPOSIT' AND l.createdby='claude_sigam_20260910'
JOIN deposits d ON d.locationid = l.locationid;

SELECT 'new locations' t, count(*) n FROM locations WHERE createdby='claude_sigam_20260910'
UNION ALL SELECT 'new deposits', count(*) FROM deposits WHERE createdby='claude_sigam_20260910'
UNION ALL SELECT 'new commodities', count(*) FROM deposit_commodities WHERE createdby='claude_sigam_20260910'
UNION ALL SELECT 'new mineralogy', count(*) FROM deposit_mineralogy WHERE createdby='claude_sigam_20260910'
UNION ALL SELECT 'new deposits w/ type', count(*) FROM deposits WHERE createdby='claude_sigam_20260910' AND deposit_type_id IS NOT NULL;

COMMIT;