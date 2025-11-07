import json
import os
import time
from datetime import datetime

import gspread
from flask import Flask, jsonify, request
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# Cache, um Google-Sheets-Reads zu reduzieren
sheet_cache = {"data": None, "timestamp": 0}


def format_decimal(value):
    """Konvertiert Zahlen in Strings mit Komma als Dezimaltrennzeichen."""
    if value is None:
        return ''
    value_str = str(value).strip()
    if value_str == '':
        return ''
    normalized = value_str.replace(':', '.').replace(' ', '')
    try:
        float(normalized)
        return normalized.replace('.', ',')
    except ValueError:
        return value_str


def parse_decimal(value):
    """Konvertiert Strings mit deutschem Dezimalformat in Float."""
    if value is None:
        return 0.0
    value_str = str(value).strip()
    if value_str == '':
        return 0.0
    normalized = value_str.replace(' ', '').replace('.', '').replace(',', '.').replace(':', '.')
    try:
        return float(normalized)
    except ValueError:
        return 0.0


def get_google_sheet():
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
    current_time = time.time()
    if current_time - sheet_cache["timestamp"] > 5 or sheet_cache["data"] is None:
        sheet_cache["data"] = sheet.get_all_values()
        sheet_cache["timestamp"] = current_time


def find_next_free_row(sheet):
    refresh_sheet_cache(sheet)
    all_values = sheet_cache["data"]
    for row_idx in range(1, len(all_values) + 100):
        if row_idx >= len(all_values):
            return row_idx + 1
        row = all_values[row_idx]
        if all((col_idx >= len(row) or row[col_idx].strip() == '') for col_idx in range(8)):
            return row_idx + 1
    return len(all_values) + 1


def get_existing_tickets(sheet):
    refresh_sheet_cache(sheet)
    return [row[1] for row in sheet_cache["data"] if len(row) > 1 and row[1]]


def get_last_balance_cached():
    try:
        if sheet_cache["data"]:
            for row in reversed(sheet_cache["data"]):
                if len(row) > 22 and row[22]:
                    return parse_decimal(row[22])
                if len(row) > 23 and row[23]:
                    return parse_decimal(row[23])
    except Exception:
        pass
    return 0.0


def invalidate_cache():
    sheet_cache["data"] = None
    sheet_cache["timestamp"] = 0


def balance_column_for_symbol(symbol):
    symbol_lower = (symbol or '').lower()
    return 'W' if any(x in symbol_lower for x in ['btc', 'eth', 'usd']) else 'X'


@app.before_request
def handle_method_override():
    if request.headers.get('X-HTTP-Method-Override') == 'PUT':
        request.environ['REQUEST_METHOD'] = 'PUT'


@app.route('/', methods=['GET'])
def root():
    action = (request.args.get('action') or '').lower()

    sheet = get_google_sheet()
    if not sheet:
        return jsonify({"error": "Sheet konnte nicht geöffnet werden"}), 500

    if action == 'check_ticket':
        ticket = (request.args.get('ticket') or '').strip()
        if not ticket:
            return jsonify({"error": "Ticket fehlt"}), 400

        refresh_sheet_cache(sheet)
        for idx, row in enumerate(sheet_cache["data"]):
            if len(row) > 1 and str(row[1]).strip() == ticket:
                return jsonify({"found": "true", "row": idx + 1})
        return jsonify({"found": "false"})

    refresh_sheet_cache(sheet)
    all_values = sheet_cache["data"]

    for idx in range(1, len(all_values)):
        row = all_values[idx]
        status = row[24].strip().upper() if len(row) > 24 else ''
        if status == 'OK':
            symbol = row[3].strip().lower() if len(row) > 3 else ''
            side = row[4].strip().upper() if len(row) > 4 else ''
            tp = parse_decimal(row[6]) if len(row) > 6 else 0.0
            sl = parse_decimal(row[7]) if len(row) > 7 else 0.0
            lots = parse_decimal(row[21]) if len(row) > 21 else 0.0

            return jsonify({
                "status": "OK",
                "row": idx + 1,
                "symbol": symbol,
                "side": side,
                "tp": tp,
                "sl": sl,
                "lots": lots
            }), 200

    return jsonify({"status": "WAIT"}), 200


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
            return jsonify({"error": "Ungültiger Side-Wert"}), 400

        entry = format_decimal(data.get('entry', ''))
        tp = format_decimal(data.get('tp', ''))
        sl = format_decimal(data.get('sl', ''))

        ticket = f"TV_{int(time.time())}"

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
            (f'V{next_row}', [['']]),
            (f'Y{next_row}', [['PENDING']]),
        ]
        for cell, value in updates:
            sheet.update(cell, value)

        balance = get_last_balance_cached()
        balance_col = balance_column_for_symbol(symbol)
        sheet.update(f'{balance_col}{next_row + 1}', [[format_decimal(balance)]])

        invalidate_cache()

        print(f"✅ TradingView Signal {ticket} → Zeile {next_row}")
        return jsonify({"status": "OK", "row": next_row, "ticket": ticket}), 200

    except Exception as e:
        print(f"❌ Fehler in tradingview_webhook: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/', methods=['POST'])
def post_dispatch():
    try:
        data = get_json_from_request()
        if not data:
            return jsonify({"error": "Keine JSON-Daten empfangen"}), 400

        print(f"POST empfangen: {data}")

        sheet = get_google_sheet()
        if not sheet:
            return jsonify({"error": "Sheet konnte nicht geöffnet werden"}), 500

        action = (data.get('action') or '').lower()

        if action == 'mark_executed':
            row = int(data.get('row', 0))
            ticket = str(data.get('ticket', ''))
            if row <= 0:
                return jsonify({"error": "Ungültige Zeile"}), 400
            sheet.update(f'Y{row}', [['EXECUTED']])
            if ticket:
                sheet.update(f'B{row}', [[ticket]])
            invalidate_cache()
            return jsonify({"ok": True}), 200

        if action == 'add_manual_trade':
            ticket = str(data.get('ticket', ''))
            if not ticket:
                return jsonify({"error": "Kein Ticket"}), 400

            existing = get_existing_tickets(sheet)
            if ticket in existing:
                print(f"⚠️ Duplikat: {ticket}")
                return jsonify({"ok": True, "message": "Trade bereits vorhanden"}), 200

            next_row = find_next_free_row(sheet)
            timestamp = datetime.now().strftime("%Y.%m.%d %H:%M:%S")
            symbol = str(data.get('symbol', '')).lower()
            side = str(data.get('side', '')).upper()
            price = format_decimal(data.get('price', ''))
            volume = format_decimal(data.get('volume', ''))

            sheet.update(f'A{next_row}:H{next_row}', [[
                timestamp,
                ticket,
                '',
                symbol,
                side,
                price,
                '',
                ''
            ]])
            sheet.update(f'V{next_row}', [[volume]])
            sheet.update(f'Y{next_row}', [['EXECUTED']])

            invalidate_cache()
            return jsonify({"ok": True, "row": next_row}), 200

        if action == 'update_trade_result':
            row = int(data.get('row', 0))
            if row <= 0:
                return jsonify({"error": "Ungültige Zeile"}), 400

            exit_reason = data.get('exitReason', 'CLOSED') or 'CLOSED'
            exit_time = data.get('exitTime', '')
            balance = data.get('balance', '')

            if exit_time:
                sheet.update(f'N{row}', [[exit_time]])
            sheet.update(f'Y{row}', [[exit_reason]])

            symbol_cell = sheet.cell(row, 4).value
            balance_col = balance_column_for_symbol(symbol_cell)
            sheet.update(f'{balance_col}{row + 1}', [[format_decimal(balance)]])

            invalidate_cache()
            return jsonify({"ok": True}), 200

        # Standard: MT5 sendet neuen Trade (Entry)
        ticket = str(data.get('ticket', ''))
        if not ticket:
            return jsonify({"error": "Kein Ticket angegeben"}), 400

        existing_tickets = get_existing_tickets(sheet)
        if ticket in existing_tickets:
            print(f"⚠️ Duplikat: {ticket}")
            return jsonify({"error": "Trade bereits vorhanden"}), 400

        next_row = find_next_free_row(sheet)
        symbol = str(data.get('symbol', '')).lower()

        sheet.update(f'A{next_row}:H{next_row}', [[
            data.get('timestamp', ''),
            ticket,
            '',
            symbol,
            str(data.get('side', '')).upper(),
            format_decimal(data.get('entry_price', '')),
            format_decimal(data.get('tp', '')),
            format_decimal(data.get('sl', ''))
        ]])
        sheet.update(f'V{next_row}', [[format_decimal(data.get('lots', data.get('balance', '')))]])
        sheet.update(f'Y{next_row}', [['EXECUTED']])

        balance_col = balance_column_for_symbol(symbol)
        sheet.update(f'{balance_col}{next_row + 1}', [[format_decimal(data.get('balance', ''))]])

        invalidate_cache()
        return jsonify({"ok": True, "row": next_row}), 200

    except Exception as e:
        print(f"❌ Fehler in POST: {e}")
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
        sheet.update(f'P{row_index}', [[format_decimal(data.get('exit_price', ''))]])
        sheet.update(f'Y{row_index}', [['CLOSED']])
        sheet.update(f'Z{row_index}', [[format_decimal(data.get('profit', ''))]])

        symbol_cell = sheet.cell(row_index, 4).value
        balance_col = balance_column_for_symbol(symbol_cell)
        sheet.update(f'{balance_col}{row_index + 1}', [[format_decimal(data.get('balance', ''))]])

        invalidate_cache()
        return jsonify({"ok": True, "row": row_index}), 200

    except Exception as e:
        print(f"❌ Fehler in UPDATE: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
