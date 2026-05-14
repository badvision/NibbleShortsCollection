1  REM  5/31/08
5 X = 5.92832: GOSUB 10: PRINT "ROUNDED TO 2 PLACES AND PADDED TO 12    CHARACTERS:": PRINT X$: END 
10 X$ =  STR$( INT(X * 100 + .5) / 100):L =  LEN(X$):M =  LEN( STR$( INT(X))):X$ =  CHR$(48 * (M$ = "0")) + X$ +  CHR$(48 * (L - M = 1)) +  CHR$(46 * (L - M = 0)) +  CHR$(48 * (L - M = 0)) +  CHR$(48 * (L - M = 0 OR L - M = 2 AND X =  > .99)):X$ = X$ +  CHR$(0): FOR I = 1 TO  LEN(X$): ON  MID$ (X$,I,1) =  CHR$(0) GOTO 20:Y$ = Y$ +  MID$ (X$,I,1)
20  NEXT :X$ = Y$:Y$ = "":X$ =  RIGHT$("         " + X$,12): RETURN : REM ROUNDIT ROUNDS/FORMATS INPUT<X>  OUTPUT <XX.00>