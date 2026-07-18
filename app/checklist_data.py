"""Template Quality Check — sama untuk beli & jual, iPhone & Android."""

# type: bool (OK / Bermasalah + note jika bad) | percent
QC_TEMPLATE: list[dict] = [
    # Tombol & biometrik
    {"group": "Tombol & biometrik", "key": "tombol_volume", "label": "Tombol Volume", "type": "bool"},
    {"group": "Tombol & biometrik", "key": "tombol_power", "label": "Tombol Power", "type": "bool"},
    {"group": "Tombol & biometrik", "key": "fingerprint_home_faceid", "label": "Fingerprint / Home / Face ID", "type": "bool"},
    {"group": "Tombol & biometrik", "key": "sensor_proximity", "label": "Sensor Proximity", "type": "bool"},
    {"group": "Tombol & biometrik", "key": "true_tone", "label": "True Tone", "type": "bool"},
    {"group": "Tombol & biometrik", "key": "flash_senter", "label": "Flash / Senter", "type": "bool"},
    {"group": "Tombol & biometrik", "key": "kompas", "label": "Kompas", "type": "bool"},
    # Audio & kamera
    {"group": "Audio & kamera", "key": "mikrofon", "label": "Mikrofon (telepon / kamera)", "type": "bool"},
    {"group": "Audio & kamera", "key": "kamera_depan_belakang", "label": "Kamera depan & belakang", "type": "bool"},
    {"group": "Audio & kamera", "key": "speaker_dering", "label": "Suara / speaker (dering)", "type": "bool"},
    {"group": "Audio & kamera", "key": "getar_silent", "label": "Getar / tombol silent", "type": "bool"},
    # Layar & body
    {"group": "Layar & body", "key": "touchscreen", "label": "Touchscreen (freeze / tidak responsif)", "type": "bool"},
    {"group": "Layar & body", "key": "layar_scratch", "label": "Layar scratch / retak / white spot", "type": "bool"},
    {"group": "Layar & body", "key": "body_lecet", "label": "Body lecet / penyok / dent", "type": "bool"},
    {"group": "Layar & body", "key": "layar_kondisi", "label": "Kondisi layar keseluruhan (%)", "type": "percent"},
    {"group": "Layar & body", "key": "body_kondisi", "label": "Kondisi body keseluruhan (%)", "type": "percent"},
    {"group": "Layar & body", "key": "battery_health", "label": "Battery Health (%)", "type": "percent"},
    # Konektivitas
    {"group": "Konektivitas & akun", "key": "wifi_bt", "label": "WiFi / Bluetooth", "type": "bool"},
    {"group": "Konektivitas & akun", "key": "jaringan_4g", "label": "Jaringan 4G/LTE", "type": "bool"},
    {"group": "Konektivitas & akun", "key": "all_provider", "label": "All Provider", "type": "bool"},
    {"group": "Konektivitas & akun", "key": "wifi_only", "label": "WiFi Only", "type": "bool"},
    {"group": "Konektivitas & akun", "key": "bea_cukai", "label": "Bea Cukai", "type": "bool"},
    {"group": "Konektivitas & akun", "key": "icloud_kosong", "label": "iCloud / akun Google kosong", "type": "bool"},
    {"group": "Konektivitas & akun", "key": "airdrop", "label": "AirDrop / Nearby Share", "type": "bool"},
    # Aksesoris
    {"group": "Aksesoris", "key": "aksesoris", "label": "Aksesoris (charger / earphone / dll.)", "type": "bool"},
]
