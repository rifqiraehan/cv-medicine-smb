import paho.mqtt.client as mqtt
import base64
import ssl
from PIL import Image
import io
import google.generativeai as genai
import json
from datetime import datetime
import os

try:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY tidak ditemukan di environment variables.")
    genai.configure(api_key=api_key)

    gemini_model = genai.GenerativeModel('gemini-2.5-flash')
except Exception as e:
    gemini_model = None
    print(f"❌ Gagal mengkonfigurasi atau memuat model: {e}")

broker = os.getenv("MQTT_BROKER", "8bda2df24fea4d2c9aadeb89eedd2738.s1.eu.hivemq.cloud")
port = int(os.getenv("MQTT_PORT", 8883))
username = os.getenv("MQTT_USERNAME")
password = os.getenv("MQTT_PASSWORD")
client_id = "Heroku_Worker_001"
topic = os.getenv("TOPIC_MAIN")
topic_detection = os.getenv("TOPIC_DETECTION")

if not all([username, password]):
    print("❌ MQTT_USERNAME atau MQTT_PASSWORD tidak ditemukan di environment variables.")
    exit()

def get_gemini_analysis(image_pil):
    """Analisis gambar menggunakan Gemini dengan prompt khusus."""
    if gemini_model is None:
        return False, -1, "Model AI tidak tersedia."

    try:
        prompt = """
        Kamu diberikan gambar kemasan obat atau nama obat itu sendiri. Tugasmu adalah menganalisis gambar tersebut dan memberikan informasi berikut dalam format JSON **valid**:

        - "Nama_Obat": Nama obat yang terlihat di gambar.
        - "Fungsi_Obat": Fungsi utama obat tersebut (misalnya: meredakan demam, mengobati infeksi, dll.) dibatasi 1 kalimat dan diringkas maksimal 5 kata saja.
        - "Cara_penggunaan": Cara penggunaan umum berdasarkan informasi di internet (misal: diminum 2x sehari, diminum 3x sehari, dll.), rangkum jadi 20 huruf.

        ⚠️ Jika nama obat tidak ada di internet atau tidak valid, tuliskan  int "0".

        Contoh output yang valid:
        {
            "Nama_Obat": "Paracetamol",
            "Fungsi_Obat": "demam dan nyeri",
            "Cara_penggunaan": "3-4 kali sehari"
        }
        contoh output yang valid lainnya:
        {
            "Nama_Obat": "Lodia",
            "Fungsi_Obat": "Diare akut dan kronis",
            "Cara_penggunaan": "2 kali sehari"
        }
        contoh output yang valid lainnya:
        {
            "Nama_Obat": "Demacolin",
            "Fungsi_Obat": "Pilek dan flu berdahak",
            "Cara_penggunaan": "3 kali sehari"
        }
        contoh output jika nama obat tidak valid atau tidak ada dalam internet:
        {
            "Nama_Obat": "0",
            "Fungsi_Obat": "0",
            "Cara_penggunaan": "0"
        }

        Hanya berikan output dalam format JSON. Jangan menambahkan penjelasan atau teks lain.
        """
        response = gemini_model.generate_content([prompt, image_pil])
        response.resolve()

        json_str_match = response.text.strip()
        if json_str_match.startswith("```json"):
            json_str_match = json_str_match[7:]
        if json_str_match.endswith("```"):
            json_str_match = json_str_match[:-3]
        json_str_match = json_str_match.strip()

        result_json = json.loads(json_str_match)
        nama = result_json.get("Nama_Obat")
        fungsi = result_json.get("Fungsi_Obat")
        cara = result_json.get("Cara_penggunaan")

        return True, 0, {
            "Nama_Obat": nama,
            "Fungsi_Obat": fungsi,
            "Cara_penggunaan": cara
        }

    except json.JSONDecodeError:
        error_msg = "Gagal memparsing respons JSON dari AI."
        print(f"Raw Gemini Response: {response.text}")
        return False, -1, error_msg
    except Exception as e:
        error_msg = f"Terjadi kesalahan saat analisis Gemini: {e}"
        return False, -1, error_msg

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ Terhubung ke MQTT broker!")
        client.subscribe(topic)
    else:
        print(f"❌ Gagal konek, kode error: {rc}")

def on_message(client, userdata, msg):
    print(f"\n📥 Pesan diterima dari topik '{msg.topic}'")

    try:
        image_data = base64.b64decode(msg.payload)
        image_pil = Image.open(io.BytesIO(image_data))

        success, _, result = get_gemini_analysis(image_pil)

        if success:
            result["timestamp"] = datetime.utcnow().isoformat()
            print(f"✅ Analisis berhasil: {json.dumps(result, indent=2)}")
            client.publish(topic_detection, json.dumps(result))
            print(f"📤 Hasil analisis dikirim ke topik '{topic_detection}'")
        else:
            print(f"❌ Analisis gagal: {result}")

    except Exception as e:
        print(f"❌ Gagal decode/proses gambar: {e}")

client = mqtt.Client(client_id=client_id)
client.username_pw_set(username, password)
client.tls_set(cert_reqs=ssl.CERT_NONE)
client.tls_insecure_set(True)

client.on_connect = on_connect
client.on_message = on_message

print("🚀 Menjalankan koneksi ke MQTT broker...")
client.connect(broker, port)
client.loop_forever()