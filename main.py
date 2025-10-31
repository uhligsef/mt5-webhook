from flask import Flask, request, jsonify
from datetime import datetime
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json

app = Flask(__name__)

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

@app.route('/', methods=['GET'])
def test():
    action = request.args.get('action', '')
    
    if action == 'test':
        # Teste Sheet-Verbindung
        sheet = get_google_sheet()
        if sheet:
            return jsonify({
                "status": "OK",
                "message": "Verbindung erfolgreich - Sheet verbunden",
                "timestamp": datetime.now().isoformat()
            })
        else:
            return jsonify({
                "status": "ERROR",
                "message": "Sheet-Verbindung fehlgeschlagen"
            }), 500
    
    return jsonify({
        "status": "OK",
        "message": "MT5 Webhook Server läuft"
    })

@app.route('/', methods=['POST'])
def add_trade():
    try:
        data = request.get_json()
        
        if data.get('action') == 'add_manual_trade':
            sheet = get_google_sheet()
            if not sheet:
                return jsonify({"error": "Sheet nicht verfügbar"}), 500
            
            # Finde nächste freie Zeile
            all_values = sheet.get_all_values()
            next_row = len(all_values) + 1
            
            # Daten vorbereiten
            ticket = data.get('ticket', '')
            symbol = data.get('symbol', '').lower()
            side = data.get('side', '')
            price = data.get('price', 0)
            volume = data.get('volume', 0)
            timestamp = datetime.now().strftime('%d.%m.%Y %H:%M:%S')
            
            # Schreibe in Sheet (Spalten A-H)
            # A: Timestamp, B: Ticket, C: leer, D: Symbol, E: Side, F: Entry, G: TP (0), H: SL (0)
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
            
            # Schreibe Daten
            sheet.update(f'A{next_row}:H{next_row}', [row_data])
            
            # Setze Status auf EXECUTED (Spalte X = 24)
            sheet.update(f'X{next_row}', 'EXECUTED')
            
            # Setze Lots (Spalte V = 22)
            sheet.update(f'V{next_row}', volume)
            
            print(f"✅ Trade in Zeile {next_row} geschrieben: Ticket {ticket}, {symbol} {side}")
            
            return jsonify({
                "ok": True,
                "message": "Trade erfolgreich ins Sheet geschrieben",
                "row": next_row,
                "ticket": ticket
            })
        else:
            return jsonify({"error": "Unbekannte Aktion"}), 400
            
    except Exception as e:
        print(f"❌ Fehler: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/trades', methods=['GET'])
def get_trades():
    try:
        sheet = get_google_sheet()
        if not sheet:
            return jsonify({"error": "Sheet nicht verfügbar"}), 500
        
        all_values = sheet.get_all_values()
        
        return jsonify({
            "trades": all_values[-10:],  # Letzte 10 Trades
            "count": len(all_values)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
