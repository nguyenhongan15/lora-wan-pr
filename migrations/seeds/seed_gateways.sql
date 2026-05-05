-- Seed 11 LoRa gateways trên địa bàn TP. Đà Nẵng (mock data cho v2 demo).
-- Toạ độ chọn theo địa danh thực; tham số antenna/TX là giả định hợp lý
-- (LoRa EU868: TX 14-17 dBm, antenna gain 2-8 dBi, độ cao 10-40m).
-- Chạy bằng: psql $DATABASE_URL -f migrations/seeds/seed_gateways.sql

DELETE FROM geo.gateways WHERE code LIKE 'DAD-%' OR code IN ('HCM-001', 'HAN-001');

INSERT INTO geo.gateways
    (code, name, location, altitude_m, antenna_height_m, antenna_gain_dbi, tx_power_dbm, frequency_mhz, owner_org, is_public)
VALUES
    -- High-elevation hilltop & mountain sites (good macro coverage)
    ('DAD-001', 'Bán đảo Sơn Trà',
     ST_SetSRID(ST_MakePoint(108.3000, 16.1180), 4326)::geography,
     693, 15, 8.0, 17.0, 868.0, 'demo-org', true),
    ('DAD-002', 'Bà Nà Hills',
     ST_SetSRID(ST_MakePoint(107.9886, 15.9981), 4326)::geography,
     1487, 12, 8.0, 17.0, 868.0, 'demo-org', true),

    -- Urban core / iconic landmarks (rooftop installations)
    ('DAD-003', 'Cầu Rồng (trung tâm)',
     ST_SetSRID(ST_MakePoint(108.2275, 16.0613), 4326)::geography,
     8, 35, 5.0, 14.0, 868.0, 'demo-org', true),
    ('DAD-004', 'Hải Châu (trung tâm hành chính)',
     ST_SetSRID(ST_MakePoint(108.2208, 16.0667), 4326)::geography,
     10, 40, 5.0, 14.0, 868.0, 'demo-org', true),
    ('DAD-005', 'Thanh Khê',
     ST_SetSRID(ST_MakePoint(108.1900, 16.0640), 4326)::geography,
     6, 30, 5.0, 14.0, 868.0, 'demo-org', true),

    -- Đại học & sân bay
    ('DAD-006', 'Đại học Đà Nẵng',
     ST_SetSRID(ST_MakePoint(108.2150, 16.0721), 4326)::geography,
     9, 25, 5.0, 14.0, 868.0, 'demo-org', true),
    ('DAD-007', 'Sân bay Quốc tế Đà Nẵng',
     ST_SetSRID(ST_MakePoint(108.1992, 16.0439), 4326)::geography,
     7, 28, 6.0, 14.0, 868.0, 'demo-org', true),

    -- Vùng ven & các quận xa trung tâm
    ('DAD-008', 'Ngũ Hành Sơn',
     ST_SetSRID(ST_MakePoint(108.2625, 16.0040), 4326)::geography,
     12, 22, 5.0, 14.0, 868.0, 'demo-org', true),
    ('DAD-009', 'Liên Chiểu',
     ST_SetSRID(ST_MakePoint(108.1500, 16.0728), 4326)::geography,
     5, 30, 5.0, 14.0, 868.0, 'demo-org', true),
    ('DAD-010', 'Cẩm Lệ',
     ST_SetSRID(ST_MakePoint(108.1985, 16.0204), 4326)::geography,
     8, 25, 5.0, 14.0, 868.0, 'demo-org', true),
    ('DAD-011', 'Hoà Vang (huyện)',
     ST_SetSRID(ST_MakePoint(108.0810, 15.9849), 4326)::geography,
     20, 30, 6.0, 17.0, 868.0, 'demo-org', true)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    location = EXCLUDED.location,
    altitude_m = EXCLUDED.altitude_m,
    antenna_height_m = EXCLUDED.antenna_height_m,
    antenna_gain_dbi = EXCLUDED.antenna_gain_dbi,
    tx_power_dbm = EXCLUDED.tx_power_dbm,
    frequency_mhz = EXCLUDED.frequency_mhz;
