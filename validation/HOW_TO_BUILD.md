# validation/reference_check.xlsx (you build this; Gate 1)

1. Run 3 real pairs in the app (suggested: Atorvastatin–RHABDOMYOLYSIS, one pair with a < 5,
   one pair that meets 0 rules). Note a, b, c, d from the 2x2 detail panel and the extraction ID.
2. In Excel, from a, b, c, d only, compute: PRR and 95% CI, ROR and 95% CI, Yates chi-square, E, IC, IC025.
   Yates chi-square: =N*MAX(ABS(a*d-b*c)-N/2,0)^2/((a+b)*(c+d)*(a+c)*(b+d))
   IC: =LOG((a+0.5)/(E+0.5),2)   IC025: =IC-3.3*(a+0.5)^-0.5-2*(a+0.5)^-1.5
3. Compare with the app to 2 decimals. Record the extraction ID and openFDA data date beside each pair.
