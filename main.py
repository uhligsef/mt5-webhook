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
        data = request.get_json()
        print(f"📥 POST empfangen: {data}")
        
        if data.get('action') == 'add_manual_trade':
            sheet = get_google_sheet()
            if not sheet:
                return jsonify({"error": "Sheet nicht verfügbar"}), 500
            
            ticket = data.get('ticket', '')
            
            # ===== DUPLIKAT-CHECK =====
            all_values = sheet.get_all_values()
            for i, row in enumerate(all_values):
                if len(row) > 1 and str(row[1]).strip() == str(ticket).strip():
                    print(f"⚠️ Ticket {ticket} existiert bereits in Zeile {i+1}")
                    response = jsonify({
                        "ok": True,
                        "message": "Trade bereits vorhanden (Duplikat verhindert)",
                        "ticket": ticket
                    })
                    response.headers['Content-Encoding'] = 'identity'
                    response.headers['Content-Type'] = 'application/json'
                    return response
            
            # Finde nächste freie Zeile
            next_row = len(all_values) + 1
            
            # Daten vorbereiten
            symbol = data.get('symbol', '').lower()
            side = data.get('side', '')
            price = data.get('price', 0)
            volume = data.get('volume', 0)
            balance = data.get('balance', 0)
            timestamp = datetime.now().strftime('%d.%m.%Y %H:%M:%S')
            
            is_crypto = symbol in ['btcusd', 'ethusd', 'bchusd', 'ltcusd', 'xrpusd']
            
            # ===== ZEILE 1: TRADE-DATEN (A-H, V, Y) OHNE Balance =====
            row_data = [
                timestamp,      # A: Datum/Zeit
                str(ticket),    # B: Ticket
                '',             # C: leer
                symbol,         # D: Symbol
                side,           # E: Side (B/S)
                price,          # F: Entry Price
                0,              # G: TP
                0               # H: SL
            ]
            
            sheet.update(f'A{next_row}:H{next_row}', [row_data])
            sheet.update(f'V{next_row}', volume)     # Spalte V: Lots
            sheet.update(f'Y{next_row}', 'EXECUTED') # Spalte Y: Status
            
            # ===== ZEILE 2: NUR KONTOSTAND (eine Zeile drunter) =====
            balance_row = next_row + 1
            
            if is_crypto:
                sheet.update(f'W{balance_row}', balance)
                print(f"✅ Crypto-Balance {balance} in W{balance_row}")
            else:
                sheet.update(f'X{balance_row}', balance)
                print(f"✅ Forex-Balance {balance} in X{balance_row}")
            
            print(f"✅ Trade in Zeile {next_row}, Balance in Zeile {balance_row}")
            
            response = jsonify({
                "ok": True,
                "message": "Trade und Balance erfolgreich geschrieben",
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
        return jsonify({"error": str(e)}), 500

# ========== PUT: TRADE SCHLIESSEN ==========
@app.route('/', methods=['PUT'])
def update_trade():
    try:
        data = request.get_json()
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
            
            print(f"🔍 Suche nach Ticket: {ticket} (Typ: {type(ticket)})")
            
            # Finde Trade-Zeile anhand Ticket
            all_values = sheet.get_all_values()
            target_row = None
            
            # DEBUG: Zeige alle Tickets im Sheet
            print(f"📋 Alle Tickets im Sheet:")
            for i, row in enumerate(all_values):
                if len(row) > 1 and row[1]:  # Spalte B
                    print(f"  Zeile {i+1}: '{row[1]}' (Typ: {type(row[1])})")
            
            for i, row in enumerate(all_values):
                if len(row) > 1:
                    sheet_ticket = str(row[1]).strip()
                    search_ticket = str(ticket).strip()
                    
                    if sheet_ticket == search_ticket:
                        target_row = i + 1
                        print(f"✅ Trade {ticket} gefunden in Zeile {target_row}")
                        break
            
            if not target_row:
                error_msg = f"Trade {ticket} nicht gefunden! Vorhandene Tickets: {[row[1] for row in all_values if len(row) > 1 and row[1]]}"
                print(f"❌ {error_msg}")
                return jsonify({"error": error_msg}), 404
            
            is_crypto = symbol in ['btcusd', 'ethusd', 'bchusd', 'ltcusd', 'xrpusd']
            balance_row = target_row + 1  # Kontostand ist eine Zeile drunter
            
            # ===== UPDATE TRADE-ZEILE (Exit-Daten) =====
            print(f"📝 Schreibe Exit-Daten in Zeile {target_row}")
            sheet.update(f'N{target_row}', exit_time)    # Spalte N: Exit Time
            sheet.update(f'P{target_row}', exit_price)   # Spalte P: Exit Price
            sheet.update(f'Y{target_row}', 'CLOSED')     # Spalte Y: Status
            sheet.update(f'Z{target_row}', profit)       # Spalte Z: Profit/Loss
            
            # ===== UPDATE BALANCE-ZEILE (eine drunter) =====
            if is_crypto:
                sheet.update(f'W{balance_row}', balance_after)
                print(f"✅ Crypto-Balance aktualisiert: {balance_after} in W{balance_row}")
            else:
                sheet.update(f'X{balance_row}', balance_after)
                print(f"✅ Forex-Balance aktualisiert: {balance_after} in X{balance_row}")
            
            print(f"✅ Trade {ticket} geschlossen: Exit {exit_price}, Profit {profit}€")
            
            response = jsonify({
                "ok": True,
                "message": "Trade-Exit erfolgreich",
                "ticket": ticket,
                "trade_row": target_row,
                "balance_row": balance_row
            })
            response.headers['Content-Encoding'] = 'identity'
            response.headers['Content-Type'] = 'application/json'
            return response
        else:
            return jsonify({"error": "Unbekannte Aktion"}), 400
            
    except Exception as e:
        print(f"❌ PUT Fehler: {str(e)}")
        import traceback
        traceback.print_exc()
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
