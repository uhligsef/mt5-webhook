from flask import Flask, request, jsonify
from datetime import datetime
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json

app = Flask(__name__)

# Disable compression
app.config['COMPRESS_REGISTER'] = False

# ========== HTTP METHOD OVERRIDE FÜR PUT ==========
@app.before_request
def handle_method_override():
    if request.headers.get('X-HTTP-Method-Override') == 'PUT':
        request.environ['REQUEST_METHOD'] = 'PUT'
        print("🔄 PUT-Request erkannt via X-HTTP-Method-Override")

# ========== HELPER: JSON aus Request extrahieren ==========
def get_json_from_request():
    """Extrahiert JSON aus Request, auch wenn Content-Type fehlt"""
    try:
        # Zuerst: Versuche request.get_json() mit force=True
        if request.content_type and 'json' in request.content_type.lower():
            json_data = request.get_json(silent=True, force=True)
            if json_data:
                return json_data
        
        # Zweiter Versuch: Direkt aus request.data lesen
        if request.data and len(request.data) > 0:
            try:
                data_str = request.data.decode('utf-8').strip()
                if data_str:
                    print(f"📦 Raw data empfangen: {data_str[:200]}...")  # Erste 200 Zeichen
                    return json.loads(data_str)
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                print(f"⚠️ Fehler beim Dekodieren: {str(e)}")
        
        # Dritter Versuch: Form-Daten (falls MQL5 das verwendet)
        if request.form:
            for key in request.form:
                try:
                    return json.loads(request.form[key])
                except:
                    pass
        
        print(f"⚠️ Keine Daten gefunden. Content-Type: {request.content_type}, Data-Length: {len(request.data) if request.data else 0}")
        return None
        
    except Exception as e:
        print(f"⚠️ Fehler beim JSON-Extrahieren: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return None

# Google Sheets Setup
def get_google_sheet():
    try:
        # Service Account Credentials aus Environment Variable
        creds_json = os.environ.get('GOOGLE_CREDENTIALS')
        if not creds_json:
            print("❌ GOOGLE_CREDENTIALS nicht gefunden!")
            return None
            
        creds_dict = json.loads(creds_json)
        scope = ['https://spreadsheets.google.com/feeds',
                 'https://www.googleapis.com/auth/drive']
        
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        # Öffne dein Sheet
        sheet_url = os.environ.get('SHEET_URL')
        sheet = client.open_by_url(sheet_url)
        worksheet = sheet.worksheet('Tagebuch')
        
        return worksheet
    except Exception as e:
        print(f"❌ Fehler beim Sheet-Zugriff: {str(e)}")
        return None

# ========== GET: TEST ENDPOINT ==========
@app.route('/', methods=['GET'])
def test():
    response = jsonify({
        "status": "OK",
        "message": "MT5 Webhook Server läuft",
        "timestamp": datetime.now().isoformat()
    })
    response.headers['Content-Encoding'] = 'identity'
    response.headers['Content-Type'] = 'application/json'
    return response

# ========== POST: TRADE EINTRAGEN ==========
@app.route('/', methods=['POST'])
def add_trade():
    try:
        # Verwende unsere Helper-Funktion
        data = get_json_from_request()
        
        if not data:
            print(f"⚠️ Keine Daten empfangen. Content-Type: {request.content_type}")
            print(f"⚠️ Raw data: {request.data}")
            return jsonify({"error": "Keine JSON-Daten empfangen"}), 400
        
        print(f"📥 POST empfangen: {data}")
        
        if data.get('action') == 'add_manual_trade':
            sheet = get_google_sheet()
            if not sheet:
                return jsonify({"error": "Sheet nicht verfügbar"}), 500
            
            ticket = data.get('ticket', '')
            
            # ===== OPTIMIERT: Nur Spalte B lesen (Tickets) =====
            tickets_column = sheet.col_values(2)  # Spalte B
            
            if str(ticket) in [str(t).strip() for t in tickets_column if t]:
                print(f"⚠️ Ticket {ticket} existiert bereits")
                response = jsonify({
                    "ok": True,
                    "message": "Trade bereits vorhanden",
                    "ticket": ticket
                })
                response.headers['Content-Encoding'] = 'identity'
                response.headers['Content-Type'] = 'application/json'
                return response
            
            # Finde nächste freie Zeile in Spalte A-H
            column_a = sheet.col_values(1)  # Spalte A
            next_row = len(column_a) + 1
            
            # Daten vorbereiten
            symbol = data.get('symbol', '').lower()
            side = data.get('side', '')
            price = data.get('price', 0)
            volume = data.get('volume', 0)
            balance = data.get('balance', 0)
            timestamp = datetime.now().strftime('%d.%m.%Y %H:%M:%S')
            
            is_crypto = symbol in ['btcusd', 'ethusd', 'bchusd', 'ltcusd', 'xrpusd']
            
            # ===== TRADE-DATEN (A-H, V, Y) =====
            row_data = [
                timestamp,      # A
                str(ticket),    # B
                '',             # C
                symbol,         # D
                side,           # E
                price,          # F
                0,              # G: TP
                0               # H: SL
            ]
            
            sheet.update(f'A{next_row}:H{next_row}', [row_data])
            sheet.update(f'V{next_row}', volume)
            sheet.update(f'Y{next_row}', 'EXECUTED')
            
            # ===== KONTOSTAND (eine Zeile drunter) =====
            balance_row = next_row + 1
            
            if is_crypto:
                sheet.update(f'W{balance_row}', balance)
            else:
                sheet.update(f'X{balance_row}', balance)
            
            print(f"✅ Trade {ticket} in Zeile {next_row}, Balance in {balance_row}")
            
            response = jsonify({
                "ok": True,
                "message": "Trade erfolgreich",
                "trade_row": next_row,
                "balance_row": balance_row,
                "ticket": ticket
            })
            response.headers['Content-Encoding'] = 'identity'
            response.headers['Content-Type'] = 'application/json'
            return response
        else:
            return jsonify({"error": "Unbekannte Aktion"}), 400
            
    except Exception as e:
        print(f"❌ POST Fehler: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

# ========== PUT: TRADE SCHLIESSEN ==========
@app.route('/', methods=['PUT'])
def update_trade():
    try:
        # Verwende unsere Helper-Funktion
        data = get_json_from_request()
        
        if not data:
            print(f"⚠️ Keine Daten empfangen. Content-Type: {request.content_type}")
            print(f"⚠️ Raw data: {request.data}")
            return jsonify({"error": "Keine JSON-Daten empfangen"}), 400
        
        print(f"📥 PUT empfangen: {data}")
        
        if data.get('action') == 'update_trade_exit':
            sheet = get_google_sheet()
            if not sheet:
                return jsonify({"error": "Sheet nicht verfügbar"}), 500
            
            ticket = data.get('ticket', '')
            symbol = data.get('symbol', '').lower()
            exit_price = data.get('exit_price', 0)
            exit_time = data.get('exit_time', datetime.now().strftime('%d.%m.%Y %H:%M:%S'))
            balance_after = data.get('balance', 0)
            profit = data.get('profit', 0)
            
            print(f"🔍 Suche Ticket: {ticket}")
            
            # ===== OPTIMIERT: Nur Spalte B lesen =====
            tickets_column = sheet.col_values(2)  # Spalte B
            target_row = None
            
            for i, t in enumerate(tickets_column):
                if str(t).strip() == str(ticket).strip():
                    target_row = i + 1
                    print(f"✅ Ticket {ticket} gefunden in Zeile {target_row}")
                    break
            
            if not target_row:
                print(f"❌ Ticket {ticket} nicht gefunden!")
                return jsonify({"error": f"Ticket {ticket} nicht gefunden"}), 404
            
            is_crypto = symbol in ['btcusd', 'ethusd', 'bchusd', 'ltcusd', 'xrpusd']
            balance_row = target_row + 1
            
            # ===== UPDATE TRADE-ZEILE =====
            sheet.update(f'N{target_row}', exit_time)
            sheet.update(f'P{target_row}', exit_price)
            sheet.update(f'Y{target_row}', 'CLOSED')
            sheet.update(f'Z{target_row}', profit)
            
            # ===== UPDATE BALANCE =====
            if is_crypto:
                sheet.update(f'W{balance_row}', balance_after)
            else:
                sheet.update(f'X{balance_row}', balance_after)
            
            print(f"✅ Trade {ticket} geschlossen")
            
            response = jsonify({
                "ok": True,
                "message": "Trade-Exit erfolgreich",
                "ticket": ticket
            })
            response.headers['Content-Encoding'] = 'identity'
            response.headers['Content-Type'] = 'application/json'
            return response
        else:
            return jsonify({"error": "Unbekannte Aktion"}), 400
            
    except Exception as e:
        print(f"❌ PUT Fehler: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

# ========== GET /trades: TRADES ANZEIGEN ==========
@app.route('/trades', methods=['GET'])
def get_trades():
    try:
        sheet = get_google_sheet()
        if not sheet:
            return jsonify({"error": "Sheet nicht verfügbar"}), 500
        
        all_values = sheet.get_all_values()
        
        return jsonify({
            "trades": all_values[-10:],  # Letzte 10 Zeilen
            "count": len(all_values)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
