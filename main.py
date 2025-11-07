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
        
        # Konvertiere TradingView-Format
        symbol = data.get('symbol', '').lower()  # KLEIN geschrieben
        side_tv = data.get('side', '').upper()  # "B" oder "S" behalten, nicht konvertieren
        
        if side_tv not in ['B', 'S']:
            return jsonify({"error": "Ungültiger Side-Wert. Muss 'B' oder 'S' sein"}), 400
        
        # Korrigiere TP/SL (Doppelpunkt zu Punkt)
        entry = str(data.get('entry', '')).replace(':', '.')
        tp = str(data.get('tp', '')).replace(':', '.')
        sl = str(data.get('sl', '')).replace(':', '.')
        
        # Generiere Ticket
        ticket = f"TV_{int(time.time())}"
        
        # Hole Balance (aus Cache oder Default)
        balance = 0.0
        try:
            if sheet_cache["data"]:
                all_values = sheet_cache["data"]
                for row in reversed(all_values):
                    if len(row) > 22 and row[22]:  # Spalte W
                        try:
                            balance = float(str(row[22]).replace(',', '.'))
                            break
                        except:
                            pass
                    if len(row) > 23 and row[23]:  # Spalte X
                        try:
                            balance = float(str(row[23]).replace(',', '.'))
                            break
                        except:
                            pass
        except:
            pass
        
        # Prüfe auf Duplikate (nur im Cache, kein API-Call)
        existing_tickets = []
        try:
            if sheet_cache["data"]:
                for row in sheet_cache["data"]:
                    if len(row) > 1 and row[1]:  # Spalte B
                        existing_tickets.append(str(row[1]))
        except:
            pass
        
        if ticket in existing_tickets:
            print(f"⚠️ Duplikat erkannt: Ticket {ticket}")
            return jsonify({"error": "Trade bereits vorhanden"}), 400
        
        # Finde nächste freie Zeile (optimiert)
        next_row = find_next_free_row_optimized(sheet)
        print(f"📝 Schreibe TradingView Signal in Zeile {next_row}")
        
        # Timestamp
        timestamp = datetime.now().strftime("%Y.%m.%d %H:%M:%S")
        
        # Schreibe Trade-Daten (KORRIGIERTE SPALTEN)
        updates = [
            {'range': f'A{next_row}', 'values': [[timestamp]]},      # A: Timestamp
            {'range': f'B{next_row}', 'values': [[ticket]]},         # B: Ticket (Ordernummer)
            {'range': f'C{next_row}', 'values': [['']]},             # C: Trade-Nr (LEER)
            {'range': f'D{next_row}', 'values': [[symbol]]},         # D: Symbol (KLEIN)
            {'range': f'E{next_row}', 'values': [[side_tv]]},       # E: Side ("B" oder "S")
            {'range': f'F{next_row}', 'values': [[entry]]},         # F: Entry Price
            {'range': f'G{next_row}', 'values': [[tp]]},            # G: T/P
            {'range': f'H{next_row}', 'values': [[sl]]},             # H: S/L (NICHT 0.01!)
        ]
        
        # Batch-Update
        for update in updates:
            sheet.update(update['range'], update['values'])
        
        # Status und Balance (andere Spalten)
        sheet.update(f'V{next_row}', [[str(balance)]])
        sheet.update(f'Y{next_row}', [['PENDING']])
        
        # Kontostand in nächste Zeile
        symbol_lower = symbol.lower()
        balance_col = 'W' if any(crypto in symbol_lower for crypto in ['btc', 'eth', 'usd']) else 'X'
        sheet.update(f'{balance_col}{next_row + 1}', [[str(balance)]])
        
        # Cache invalidieren
        sheet_cache["data"] = None
        sheet_cache["timestamp"] = 0
        
        print(f"✅ TradingView Signal {ticket} hinzugefügt in Zeile {next_row}")
        return jsonify({"status": "ok", "row": next_row, "ticket": ticket}), 200
        
    except Exception as e:
        print(f"❌ Fehler in tradingview_webhook: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
