import sys

sys.path.insert(0, r"C:\Users\alaga\Desktop\My Script Library\My Telegram Bot")

from execution_engine import RouteQuoteClient, WRAPPED_SOL_MINT


USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

quote = RouteQuoteClient().best_quote(WRAPPED_SOL_MINT, USDC_MINT, 1_000_000, 1500, True)
print(quote.get("provider"), quote.get("outAmount"), quote.get("routeAttempts"))
