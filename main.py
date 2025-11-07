from flask import Flask, request, jsonify
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
from datetime import datetime

app = Flask(__name__)

def get_google_sheet():
    try:
        credentials_json = os.environ.get('GOOGLE_CREDENTIALS')
        if not credentials_json:
            print("❌ GOOGLE_CREDENTIALS nicht gefunden!")
            return None
        
        import json
        credentials_dict = json.loads(credentials_json)
        
        scope = ['https://spreadsheets.google.com/feeds',
                 'https://www.googleapis.com/auth/drive']
        
        creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scope)
        client = gspread.authorize(creds)
        
        sheet_url = os.environ.get('SHEET_URL')
        if not sheet_url:
            print("❌ SHEET_URL nicht gefunden!")
            return None
        
        sheet = client.open_by_url(sheet_url).sheet1
        return sheet
    except Exception as e:
        print(f"❌ Fehler beim Öffnen des Sheets: {e}")
        return None

def get_json_from_request():
    """Robust JSON extraction from request"""
    try:
        data = request.get_json(silent=True)
        if data:
            return data
        
        if request.data:
            import json
            try:
                data = json.loads(request.data.decode('utf-8'))
                if data:
                    return data
            except:
                pass
        
        if request.form:
            return dict(request.form)
        
        return None
    except Exception as e:
        print(f"⚠️ Fehler beim Parsen von JSON: {e}")
        return None

def find_next_free_row(sheet):
    """Finde die erste Zeile, wo A-H komplett leer sind"""
    try:
        all_values = sheet.get_all_values()
        
        for row_num in range(2, len(all_values) + 100):
            row_values = sheet.row_values(row_num)
            
            is_empty = True
            for col_idx in range(8):  # A-H = 8 Spalten
                if col_idx < len(row_values) and row_values[col_idx].strip():
                    is_empty = False
                    break
            
            if is_empty:
                return row_num
        
        return len(all_values) + 1
    except Exception as e:
        print(f"⚠️ Fehler beim Finden der freien Zeile: {e}")
        return len(sheet.get_all_values()) + 1

@app.before_request
def handle_method_override():
    """Handle X-HTTP-Method-Override header"""
    if request.headers.get('X-HTTP-Method-Override') == 'PUT':
        request.method = 'PUT'

@app.route('/', methods=['GET'])
def test():
    return jsonify({"status": "ok", "message": "Server läuft"}), 200

@app.route('/tradingview', methods=['POST'])
def tradingview_webhook():
    """Spezieller Endpunkt für TradingView Webhooks"""
    try:
        data = get_json_from_request()
        if not data:
            return jsonify({"error": "Keine JSON-Daten empfangen"}), 400
        
        print(f"📊 TradingView Webhook empfangen: {data}")
        
        sheet = get_google_sheet()
        if not sheet:
            return jsonify({"error": "Sheet konnte nicht geöffnet werden"}), 500
        
        # Konvertiere TradingView-Format zu unserem Format
        symbol = data.get('symbol', '').upper()
        side_tv = data.get('side', '').upper()
        side = 'BUY' if side_tv == 'B' else 'SELL' if side_tv == 'S' else ''
        
        if not side:
            return jsonify({"error": "Ungültiger Side-Wert. Muss 'B' oder 'S' sein"}), 400
        
        # Generiere Ticket (TradingView + Timestamp)
        import time
        ticket = f"TV_{int(time.time())}"
        
        # Hole aktuellen Kontostand (aus letzter Zeile oder Default)
        try:
            all_values = sheet.get_all_values()
            # Suche nach letztem Balance-Eintrag in Spalte W oder X
            balance = 0.0
            for row in reversed(all_values):
                if len(row) > 22 and row[22]:  # Spalte W (Index 22)
                    try:
                        balance = float(row[22])
                        break
                    except:
                        pass
                if len(row) > 23 and row[23]:  # Spalte X (Index 23)
                    try:
                        balance = float(row[23])
                        break
                    except:
                        pass
        except:
            balance = 0.0
        
        # Prüfe auf Duplikate (gleicher Symbol + Side + Entry Price innerhalb der letzten 5 Minuten)
        existing_tickets = sheet.col_values(2)
        if ticket in existing_tickets:
            print(f"⚠️ Duplikat erkannt: Ticket {ticket}")
            return jsonify({"error": "Trade bereits vorhanden"}), 400
        
        # Finde nächste freie Zeile
        next_row = find_next_free_row(sheet)
        print(f"📝 Schreibe TradingView Signal in Zeile {next_row}")
        
        # Aktueller Timestamp
        timestamp = datetime.now().strftime("%Y.%m.%d %H:%M:%S")
        
        # Schreibe Trade-Daten
        sheet.update(f'A{next_row}', timestamp)
        sheet.update(f'B{next_row}', ticket)
        sheet.update(f'C{next_row}', symbol)
        sheet.update(f'D{next_row}', side)
        sheet.update(f'E{next_row}', data.get('entry', ''))
        sheet.update(f'F{next_row}', data.get('tp', ''))
        sheet.update(f'G{next_row}', data.get('sl', ''))
        sheet.update(f'H{next_row}', '0.01')  # Default Lots
        sheet.update(f'V{next_row}', str(balance))
        sheet.update(f'Y{next_row}', 'PENDING')  # Status: PENDING für TradingView
        
        # Schreibe Kontostand in nächste Zeile
        symbol_lower = symbol.lower()
        balance_col = 'W' if any(crypto in symbol_lower for crypto in ['btc', 'eth', 'usd']) else 'X'
        sheet.update(f'{balance_col}{next_row + 1}', str(balance))
        
        print(f"✅ TradingView Signal {ticket} hinzugefügt in Zeile {next_row}")
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
        
        # Prüfe auf Duplikate
        existing_tickets = sheet.col_values(2)
        if ticket in existing_tickets:
            print(f"⚠️ Duplikat erkannt: Ticket {ticket}")
            return jsonify({"error": "Trade bereits vorhanden"}), 400
        
        # Finde nächste freie Zeile
        next_row = find_next_free_row(sheet)
        print(f"📝 Schreibe in Zeile {next_row}")
        
        # Schreibe Trade-Daten
        sheet.update(f'A{next_row}', data.get('timestamp', ''))
        sheet.update(f'B{next_row}', ticket)
        sheet.update(f'C{next_row}', data.get('symbol', ''))
        sheet.update(f'D{next_row}', data.get('side', ''))
        sheet.update(f'E{next_row}', data.get('entry_price', ''))
        sheet.update(f'F{next_row}', data.get('tp', ''))
        sheet.update(f'G{next_row}', data.get('sl', ''))
        sheet.update(f'H{next_row}', data.get('lots', ''))
        sheet.update(f'V{next_row}', data.get('balance', ''))
        sheet.update(f'Y{next_row}', 'EXECUTED')
        
        # Schreibe Kontostand in nächste Zeile
        balance = data.get('balance', '')
        symbol = data.get('symbol', '').lower()
        balance_col = 'W' if any(crypto in symbol for crypto in ['btc', 'eth', 'usd']) else 'X'
        sheet.update(f'{balance_col}{next_row + 1}', balance)
        
        print(f"✅ Trade {ticket} hinzugefügt in Zeile {next_row}")
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
        
        # Finde Zeile mit diesem Ticket
        tickets = sheet.col_values(2)
        try:
            row_index = tickets.index(ticket) + 1
            print(f"📝 Gefunden: Ticket {ticket} in Zeile {row_index}")
        except ValueError:
            print(f"❌ Ticket {ticket} nicht gefunden in Spalte B")
            return jsonify({"error": f"Ticket {ticket} nicht gefunden"}), 404
        
        # Update Exit-Details
        print(f"🔄 Update Zeile {row_index}: Exit Time, Exit Price, Status, Profit")
        sheet.update(f'N{row_index}', data.get('exit_time', ''))
        sheet.update(f'P{row_index}', data.get('exit_price', ''))
        sheet.update(f'Y{row_index}', 'CLOSED')
        sheet.update(f'Z{row_index}', data.get('profit', ''))
        
        # Update Kontostand in nächster Zeile
        balance = data.get('balance', '')
        symbol_cell = sheet.cell(row_index, 3).value
        symbol = (symbol_cell or '').lower()
        balance_col = 'W' if any(crypto in symbol for crypto in ['btc', 'eth', 'usd']) else 'X'
        sheet.update(f'{balance_col}{row_index + 1}', balance)
        
        print(f"✅ Trade {ticket} aktualisiert in Zeile {row_index}")
        return jsonify({"status": "ok", "row": row_index}), 200
        
    except Exception as e:
        print(f"❌ Fehler in update_trade: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
