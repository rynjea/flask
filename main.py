from flask import Flask, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import re
from datetime import datetime, timedelta
import requests
import io

app = Flask(__name__)


# ======================= DATABASE =======================
def get_db_connection():
    try:
        return psycopg2.connect(host=os.getenv('DB_HOST'),
                                database=os.getenv('DB_NAME'),
                                user=os.getenv('DB_USER'),
                                password=os.getenv('DB_PASSWORD'),
                                port=os.getenv('DB_PORT', 5432),
                                cursor_factory=RealDictCursor)
    except Exception as e:
        print(f"Database connection error: {e}")
        return None


def insert_pengeluaran(user_id, kategori, nominal, deskripsi):
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pengeluaran (user_id, kategori, nominal, deskripsi, tanggal)
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                """, (user_id, kategori, nominal, deskripsi))
                conn.commit()
                return True
        except Exception as e:
            print(f"Insert error: {e}")
            conn.rollback()
        finally:
            conn.close()
    return False


def delete_pengeluaran(user_id):
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM pengeluaran WHERE user_id = %s",
                            (user_id, ))
                conn.commit()
                return True
        except Exception as e:
            print(f"Hapus error: {e}")
            conn.rollback()
        finally:
            conn.close()
    return False


def delete_by_deskripsi(user_id, keyword):
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM pengeluaran
                    WHERE user_id = %s AND deskripsi ILIKE %s
                """, (user_id, f"%{keyword}%"))
                deleted = cur.rowcount
                conn.commit()
                return deleted > 0
        except Exception as e:
            print(f"Delete by keyword error: {e}")
            conn.rollback()
        finally:
            conn.close()
    return False


def get_total_pengeluaran(user_id, start_date, end_date=None):
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                query = """
                    SELECT SUM(nominal) AS total
                    FROM pengeluaran
                    WHERE user_id = %s AND DATE(tanggal) >= %s
                """
                params = [user_id, start_date]
                if end_date:
                    query += " AND DATE(tanggal) <= %s"
                    params.append(end_date)
                cur.execute(query, tuple(params))
                result = cur.fetchone()
                return result['total'] if result and result['total'] else 0
        finally:
            conn.close()
    return 0


def get_total_per_kategori(user_id, start_date, end_date=None):
    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                query = """
                    SELECT kategori, SUM(nominal) AS total
                    FROM pengeluaran
                    WHERE user_id = %s AND DATE(tanggal) >= %s
                """
                params = [user_id, start_date]
                if end_date:
                    query += " AND DATE(tanggal) <= %s"
                    params.append(end_date)
                query += " GROUP BY kategori"
                cur.execute(query, tuple(params))
                return cur.fetchall()
        finally:
            conn.close()
    return []


# ======================= UTILITIES =======================
def kategori_otomatis(deskripsi):
    deskripsi = deskripsi.lower()
    mapping = {
        "makanan":
        ["nasi", "makan", "ayam", "kopi", "burger", "kfc", "sarapan"],
        "transportasi":
        ["grab", "gojek", "angkot", "kereta", "ojek", "bensin"],
        "listrik": ["listrik", "token", "pln"],
        "hiburan": ["spotify", "netflix", "bioskop", "game"],
        "belanja": ["shopee", "tokopedia", "lazada", "beli", "order"]
    }
    for kategori, kata in mapping.items():
        if any(k in deskripsi for k in kata):
            return kategori
    return "lainnya"


def parse_nominal(teks):
    teks = teks.lower()
    if "juta" in teks:
        match = re.search(r"(\d+[.,]?\d*)\s*juta", teks)
        if match:
            return int(float(match.group(1).replace(",", ".")) * 1_000_000)
    match = re.search(r"(\d{1,3}(?:[.,]\d{3})*|\d+)", teks)
    if match:
        return int(match.group(1).replace(".", "").replace(",", ""))
    return 0


def send_telegram_message(chat_id, text):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text})
    except Exception as e:
        print("Send Telegram error:", e)

# ======================= WEBHOOK =======================

    @app.route("/telegram-webhook", methods=["POST"])
    def telegram_webhook():
        data = request.get_json()
        chat_id = data["message"]["chat"]["id"]
        user_id = str(chat_id)
        text = data["message"].get("text") or data["message"].get(
            "caption", "")
        text = text.lower().strip()

        # proses intent dan kirim response
        send_telegram_message(chat_id, "Halo! Ini webhook aktif.")
        return jsonify({"status": "ok"})

# ======================= HOMEPAGE =======================

    @app.route("/")
    def home():
        return "Bot is running!"


# ===== INTENTS =====

    if text.startswith("hapus beli"):
        keyword = text.replace("hapus beli", "").strip()
        if delete_by_deskripsi(user_id, keyword):
            send_telegram_message(
                chat_id, f"🗑️ Pengeluaran '{keyword}' berhasil dihapus.")
        else:
            send_telegram_message(
                chat_id, f"❌ Tidak ditemukan pengeluaran '{keyword}'.")
        return jsonify({"status": "ok"})

    if any(text.startswith(w) for w in ["beli", "makan", "bayar"]):
        match = re.search(r'(beli|makan|bayar)\s+(.+?)\s+(.+)', text)
        if match:
            deskripsi = match.group(2)
            nominal = parse_nominal(match.group(3))
            kategori = kategori_otomatis(deskripsi)
            if nominal > 0:
                insert_pengeluaran(user_id, kategori, nominal, deskripsi)
                send_telegram_message(
                    chat_id,
                    f"✅ Dicatat: {deskripsi} = Rp {nominal:,} (kategori: {kategori})"
                )
            else:
                send_telegram_message(chat_id, "❗ Nominal tidak dikenali.")
        else:
            send_telegram_message(chat_id,
                                  "❌ Format salah. Contoh: beli kopi 15000")
        return jsonify({"status": "ok"})

    if "laporan bulan" in text:
        match = re.search(r"laporan bulan (\w+)", text)
        bulan_dict = {
            "januari": 1,
            "februari": 2,
            "maret": 3,
            "april": 4,
            "mei": 5,
            "juni": 6,
            "juli": 7,
            "agustus": 8,
            "september": 9,
            "oktober": 10,
            "november": 11,
            "desember": 12
        }
        if match:
            nama_bulan = match.group(1)
            if nama_bulan in bulan_dict:
                month = bulan_dict[nama_bulan]
                now = datetime.now()
                start = datetime(now.year, month, 1).date()
                end = datetime(now.year, month + 1, 1).date() - timedelta(
                    days=1) if month < 12 else datetime(now.year, 12,
                                                        31).date()
                total = get_total_pengeluaran(user_id, start, end)
                send_telegram_message(
                    chat_id,
                    f"📆 Total pengeluaran bulan {nama_bulan.capitalize()}: Rp {total:,}"
                )
            else:
                send_telegram_message(chat_id, "❌ Bulan tidak dikenali.")
        return jsonify({"status": "ok"})

    if text.startswith("laporan "):
        keyword = text.replace("laporan", "").strip()
        hasil = get_total_per_kategori(user_id,
                                       datetime.now().date().replace(day=1))
        found = False
        for h in hasil:
            if keyword in h['kategori']:
                send_telegram_message(
                    chat_id, f"📊 Total {h['kategori']}: Rp {h['total']:,}")
                found = True
                break
        if not found:
            send_telegram_message(
                chat_id,
                f"❗ Tidak ditemukan data pengeluaran untuk '{keyword}'")
        return jsonify({"status": "ok"})

    if text.strip() == "laporan":
        start = datetime.now().date().replace(day=1)
        total = get_total_pengeluaran(user_id, start)
        send_telegram_message(chat_id,
                              f"📈 Total pengeluaran bulan ini: Rp {total:,}")
        return jsonify({"status": "ok"})

    send_telegram_message(chat_id, "Maaf, aku belum paham maksud kamu 😔")
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8080)
