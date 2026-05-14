10 T$ = "DEMO MENU":C = 3:C$(1) = "QUIT":C$(2) = "RETRY":C$(3) = "BEEP": GOSUB 100: IF S = 1 THEN  END 
20  IF S = 2 THEN  GOTO 10
30  IF S = 3 THEN  PRINT  CHR$(7): GOTO 10
100  HOME : INVERSE : PRINT  TAB( 20 -  LEN(T$) / 2)T$ TAB( 40): NORMAL : PRINT : FOR I = 1 TO C: VTAB 5 + 2 * I: PRINT  SPC( 5)C$(I): NEXT : VTAB 24: PRINT "HIGHLIGHT CHOICE WITH ARROWS & <RETURN>";:S = 1:R$ =  CHR$(13):H$ =  CHR$(8):U$ =  CHR$(21)
110  VTAB 5 + S * 2: HTAB 5: INVERSE : PRINT " "C$(S)" ";: GET I$: HTAB 5: NORMAL : PRINT " "C$(S)" ";:S = S + (I$ = U$) - (I$ = H$):S = C * (S = 0) + (S = (C + 1)) + S * (S <  > 0 AND S <  > C + 1): ON (I$ = H$ OR I$ = U$) GOTO 110: RETURN 