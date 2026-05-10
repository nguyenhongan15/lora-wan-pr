-- 11 LoRaWAN gateways thực tế — deployment "3. DNIIT" (ChirpStack v4 export).
-- Source: r-dt/response_1777987688423.json (snapshot 2026-02-17, AS923-2).
--
-- Antenna metadata (height / gain / TX power) KHÔNG có trong export → dùng
-- giá trị "outdoor LoRa thực tế phổ biến": cột 15m, fiberglass omni 5 dBi,
-- TX 14 dBm (giới hạn AS923-2). Operator phải verify khi có spec thật.
-- Lý do KHÔNG dùng default bảng (10m/2dBi): default 2 dBi là PCB integrated
-- (indoor), không phản ánh gateway DNIIT thực tế triển khai outdoor.
--
-- altitude_m = 0 cho tất cả: 7/11 record trong export có altitude == longitude
-- (lỗi parser upstream), 4/11 còn lại null. Data dev sẽ fill từ DEM/khảo sát.
--
-- frequency_mhz = 923.0 vì CHECK chk_freq_lora_band của geo.gateways chỉ cho
-- 433/868/915/923. Carrier thực 921.4 MHz được lưu chính xác trong
-- ts.survey_*.frequency_mhz (table đó không có CHECK band).
--
-- Idempotent: chạy lại nhiều lần không tạo duplicate.

-- Cleanup seed cũ (mock data v0).
DELETE FROM geo.gateways WHERE code LIKE 'DAD-%' OR code IN ('HCM-001', 'HAN-001');

INSERT INTO geo.gateways
    (code, name, location, altitude_m, antenna_height_m, antenna_gain_dbi,
     tx_power_dbm, frequency_mhz, owner_org, is_public)
VALUES
    ('ac1f09fffe06fcf2', 'DNIIT GW 06fcf2',
     ST_SetSRID(ST_MakePoint(108.21985626414313, 16.054765682623003), 4326)::geography,
     0, 15, 5.0, 14.0, 923.0, 'DNIIT', true),
    ('7276ff002e06029f', 'DNIIT GW 06029f',
     ST_SetSRID(ST_MakePoint(108.1532551, 16.0659959), 4326)::geography,
     0, 15, 5.0, 14.0, 923.0, 'DNIIT', true),
    ('7276ff002e0507da', 'DNIIT GW 0507da',
     ST_SetSRID(ST_MakePoint(108.1524913, 16.0740935), 4326)::geography,
     0, 15, 5.0, 14.0, 923.0, 'DNIIT', true),
    ('a84041ffff1ec39f', 'DNIIT GW 1ec39f',
     ST_SetSRID(ST_MakePoint(108.1525171, 16.0741086), 4326)::geography,
     0, 15, 5.0, 14.0, 923.0, 'DNIIT', true),
    ('ac1f09fffe00ab25', 'DNIIT GW 00ab25',
     ST_SetSRID(ST_MakePoint(108.12857, 16.11073), 4326)::geography,
     0, 15, 5.0, 14.0, 923.0, 'DNIIT', true),
    ('ac1f09fffe0fd63b', 'DNIIT GW 0fd63b',
     ST_SetSRID(ST_MakePoint(108.23986, 15.98571), 4326)::geography,
     0, 15, 5.0, 14.0, 923.0, 'DNIIT', true),
    ('7276ff002e062cf2', 'DNIIT GW 062cf2',
     ST_SetSRID(ST_MakePoint(108.27363586425781, 16.11829376220703), 4326)::geography,
     0, 15, 5.0, 14.0, 923.0, 'DNIIT', true),
    ('7276ff002e061f5b', 'DNIIT GW 061f5b',
     ST_SetSRID(ST_MakePoint(108.22207641601562, 16.075590133666992), 4326)::geography,
     0, 15, 5.0, 14.0, 923.0, 'DNIIT', true),
    ('a840411eebb44150', 'DNIIT GW b44150',
     ST_SetSRID(ST_MakePoint(108.15253, 16.0740984), 4326)::geography,
     0, 15, 5.0, 14.0, 923.0, 'DNIIT', true),
    ('ac1f09fffe0fd629', 'DNIIT GW 0fd629',
     ST_SetSRID(ST_MakePoint(108.15448, 16.06815), 4326)::geography,
     0, 15, 5.0, 14.0, 923.0, 'DNIIT', true),
    ('ac1f09fffe00ab20', 'DNIIT GW 00ab20',
     ST_SetSRID(ST_MakePoint(108.22009, 16.05469), 4326)::geography,
     0, 15, 5.0, 14.0, 923.0, 'DNIIT', true)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    location = EXCLUDED.location,
    altitude_m = EXCLUDED.altitude_m,
    antenna_height_m = EXCLUDED.antenna_height_m,
    antenna_gain_dbi = EXCLUDED.antenna_gain_dbi,
    tx_power_dbm = EXCLUDED.tx_power_dbm,
    frequency_mhz = EXCLUDED.frequency_mhz,
    owner_org = EXCLUDED.owner_org;
