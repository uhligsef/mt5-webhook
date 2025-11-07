import os
import time
from datetime import datetime
import json

from flask import Flask, request, jsonify
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# Sheet-Cache, um API-Reads zu sparen
sheet_cache = {"data": None, "timestamp": 0}

def get_google_sheet():
    """Öffnet das Google Sheet und gibt das Worksheet zurück."""
    try:
        credentials_json = os.environ.get('GOOGLE_CREDENTIALS')
        if not credentials_json:
            print("❌ GOOGLE_CREDENTIALS nicht gefunden!")
            return None

        credentials_dict = json.loads(credentials_json)
        scope = [
            'https://spreadsheets.google.com/feeds',
            'https://www.googleapis.com/auth/drive'
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scope)
        client = gspread.authorize(creds)

        sheet_url = os.environ.get('SHEET_URL')
        if not sheet_url:
            print("❌ SHEET_URL nicht gefunden!")
            return None

        return client.open_by_url(sheet_url).sheet1
    except Exception as e:
        print(f"❌ Fehler beim Öffnen des Sheets: {e}")
        return None

def get_json_from_request():
    """Liest robuste JSON-Daten aus dem Request."""
    try:
        data = request.get_json(silent=True)
        if data:
            return data

        if request.data:
            try:
                return json.loads(request.data.decode('utf-8'))
            except Exception:
                pass

        if request.form:
            return dict(request.form)

        return None
    except Exception as e:
        print(f"⚠️ Fehler beim Parsen von JSON: {e}")
        return None

def refresh_sheet_cache(sheet):
    """Aktualisiert den Cache (max alle 5 Sekunden)."""
    current_time = time.time()
    if current_time - sheet_cache["timestamp"] > 5 or sheet_cache["data"] is None:
        sheet_cache["data"] = sheet.get_all_values()
        sheet_cache["timestamp"] = current_time

def find_next_free_row(sheet):
    """Findet die erste Zeile, in der A-H leer sind (nutzt Cache)."""
    refresh_sheet_cache(sheet)
    all_values = sheet_cache["data"]

    # Start bei Zeile 2 (Zeile 1 = Header)
    for row_idx in range(1, len(all_values) + 100):
        if row_idx >= len(all_values):
            return row_idx + 1  # neue Zeile

        row = all_values[row_idx]
        is_empty = True
        for col_idx in range(8):  # A-H
            if col_idx < len(row) and row[col_idx].strip():
                is_empty = False
                break
        if is_empty:
            return row_idx + 1

    return len(all_values) + 1

def get_existing_tickets(sheet):
    """Liest Ticket-Liste (Spalte B) – nutzt Cache wenn möglich."""
    refresh_sheet_cache(sheet)
    return [row[1] for row in sheet_cache["data"] if len(row) > 1 and row[1]]

def get_last_balance_cached():
    """Versucht, den letzten Balance-Wert aus dem Cache zu lesen."""
    try:
        if sheet_cache["data"]:
            for row in reversed(sheet_cache["data"]):
                if len(row) > 22 and row[22]:
                    return float(str(row[22]).replace(',', '.'))
                if len(row) > 23 and row[23]:
                    return float(str(row[23]).replace(',', '.'))
    except Exception:
        pass
    return 0.0

def invalidate_cache():
    sheet_cache["data"] = None
    sheet_cache["timestamp"] = 0

@app.before_request
def handle_method_override():
    if request.headers.get('X-HTTP-Method-Override') == 'PUT':
        request.method = 'PUT'

@app.route('/', methods=['GET'])
def root():
    return jsonify({"status": "ok", "message": "Server läuft"}), 200

@app.route('/tradingview', methods=['POST'])
def tradingview_webhook():
    try:
        data = get_json_from_request()
        if not data:
            return jsonify({"error": "Keine JSON-Daten empfangen"}), 400

        print(f"📊 TradingView Webhook empfangen: {data}")

        sheet = get_google_sheet()
        if not sheet:
            return jsonify({"error": "Sheet konnte nicht geöffnet werden"}), 500

        symbol = data.get('symbol', '').lower()
        side = data.get('side', '').upper()

        if side not in ['B', 'S']:
            return jsonify({"error": "Ungültiger Side-Wert (erwartet 'B' oder 'S')"}), 400

        entry = str(data.get('entry', '')).replace(':', '.')
        tp = str(data.get('tp', '')).replace(':', '.')
        sl = str(data.get('sl', '')).replace(':', '.')

        ticket = f"TV_{int(time.time())}"

        balance = get_last_balance_cached()

        existing_tickets = get_existing_tickets(sheet)
        if ticket in existing_tickets:
            print(f"⚠️ Duplikat: {ticket}")
            return jsonify({"error": "Trade bereits vorhanden"}), 400

        next_row = find_next_free_row(sheet)
        print(f"📝 TradingView: schreibe in Zeile {next_row}")

        timestamp = datetime.now().strftime("%Y.%m.%d %H:%M:%S")

        updates = [
            (f'A{next_row}', [[timestamp]]),
            (f'B{next_row}', [[ticket]]),
            (f'C{next_row}', [['']]),
            (f'D{next_row}', [[symbol]]),
            (f'E{next_row}', [[side]]),
            (f'F{next_row}', [[entry]]),
            (f'G{next_row}', [[tp]]),
            (f'H{next_row}', [[sl]]),
            (f'V{next_row}', [[str(balance)]]),
            (f'Y{next_row}', [['PENDING']]),
        ]
        for cell, value in updates:
            sheet.update(cell, value)

        balance_col = 'W' if any(x in symbol for x in ['btc', 'eth', 'usd']) else 'X'
        sheet.update(f'{balance_col}{next_row + 1}', [[str(balance)]])

        invalidate_cache()

        print(f"✅ TradingView Signal {ticket} → Zeile {next_row}")
        return jsonify({"status": "ok", "row": next_row, "ticket": ticket}), 200

    except Exception as e:
        print(f"❌ Fehler in tradingview_webhook: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/', methods=['POST'])
def add_trade():
    try:
        data = get_json_from_request()
        if not data:
            return jsonify({"error": "Keine JSON-Daten empfangen"}), 400

        print(f"POST empfangen: {data}")

        sheet = get_google_sheet()
        if not sheet:
            return jsonify({"error": "Sheet konnte nicht geöffnet werden"}), 500

        ticket = str(data.get('ticket', ''))
        if not ticket:
            return jsonify({"error": "Kein Ticket angegeben"}), 400

        existing_tickets = get_existing_tickets(sheet)
        if ticket in existing_tickets:
            print(f"⚠️ Duplikat: {ticket}")
            return jsonify({"error": "Trade bereits vorhanden"}), 400

        next_row = find_next_free_row(sheet)
        print(f"📝 MT5 Entry → Zeile {next_row}")

        sheet.update(f'A{next_row}', [[data.get('timestamp', '')]])
        sheet.update(f'B{next_row}', [[ticket]])
        sheet.update(f'C{next_row}', [['']])
        sheet.update(f'D{next_row}', [[data.get('symbol', '').lower()]])
        sheet.update(f'E{next_row}', [[data.get('side', '')]])
        sheet.update(f'F{next_row}', [[data.get('entry_price', '')]])
        sheet.update(f'G{next_row}', [[data.get('tp', '')]])
        sheet.update(f'H{next_row}', [[data.get('sl', '')]])
        sheet.update(f'V{next_row}', [[data.get('balance', '')]])
        sheet.update(f'Y{next_row}', [['EXECUTED']])

        symbol_lower = data.get('symbol', '').lower()
        balance_col = 'W' if any(x in symbol_lower for x in ['btc', 'eth', 'usd']) else 'X'
        sheet.update(f'{balance_col}{next_row + 1}', [[data.get('balance', '')]])

        invalidate_cache()

        print(f"✅ MT5 Entry {ticket} → Zeile {next_row}")
        return jsonify({"status": "ok", "row": next_row}), 200

    except Exception as e:
        print(f"❌ Fehler in add_trade: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/', methods=['PUT'])
def update_trade():
    try:
        data = get_json_from_request()
        if not data:
            return jsonify({"error": "Keine JSON-Daten empfangen"}), 400

        print(f"PUT empfangen: {data}")

        sheet = get_google_sheet()
        if not sheet:
            return jsonify({"error": "Sheet konnte nicht geöffnet werden"}), 500

        ticket = str(data.get('ticket', ''))
        if not ticket:
            return jsonify({"error": "Kein Ticket angegeben"}), 400

        tickets = sheet.col_values(2)
        try:
            row_index = tickets.index(ticket) + 1
        except ValueError:
            return jsonify({"error": f"Ticket {ticket} nicht gefunden"}), 404

        sheet.update(f'N{row_index}', [[data.get('exit_time', '')]])
        sheet.update(f'P{row_index}', [[data.get('exit_price', '')]])
        sheet.update(f'Y{row_index}', [['CLOSED']])
        sheet.update(f'Z{row_index}', [[data.get('profit', '')]])

        symbol_cell = sheet.cell(row_index, 4).value  # Spalte D jetzt Symbol
        symbol_lower = (symbol_cell or '').lower()
        balance_col = 'W' if any(x in symbol_lower for x in ['btc', 'eth', 'usd']) else 'X'
        sheet.update(f'{balance_col}{row_index + 1}', [[data.get('balance', '')]])

        invalidate_cache()

        print(f"✅ MT5 Exit {ticket} → Zeile {row_index}")
        return jsonify({"status": "ok", "row": row_index}), 200

    except Exception as e:
        print(f"❌ Fehler in update_trade: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
