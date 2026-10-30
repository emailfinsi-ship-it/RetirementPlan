"""Plain-words hover explanations for the technical terms on the Stock Analysis tab (watchlist, quote panel) and the
ratings hover on the broker tabs.

One list of terms, written for someone who does not trade for a living: what the thing is, how to read it, and what it
is NOT (none of these predicts anything). Shown in the page's shared hover box (``data-ctip`` attributes), which keeps
line breaks when the page also loads ``CSS``. Read-only text; nothing here touches an order or is advice."""

from __future__ import annotations

CSS = """
.nw-tip .nw-tip-pct { white-space:pre-line; max-width:300px; line-height:1.45; }
.has-tip { text-decoration:underline dotted; text-underline-offset:3px; cursor:help; }
"""

# Defines window.TERMS, window.termAttrs(key), window.termKeyForSignal(name) and window.macdTipAttrs(...) once per page.
JS = r"""
if (!window.termAttrs) {
  window.TERMS = {
    macd: ['MACD and its signal line',
      'MACD is a momentum gauge: a short-term average price (12 days) minus a longer one (26 days).\n' +
      'The signal line is a smoothed average (9 days) of the MACD itself, so it reacts more slowly.\n' +
      'MACD above its signal line: momentum is rising (bullish). Below: momentum is fading (bearish).\n' +
      'A crossover is the moment the two lines swap places. Traders read it as a hint that momentum has turned, not as a prediction.'],
    rsi: ['RSI (Relative Strength Index)',
      'A 0 to 100 score of recent buying versus selling pressure over the last 14 days.\n' +
      'Under 30 is "oversold": sellers may be worn out and a bounce is common.\n' +
      'Over 70 is "overbought": buyers may be stretched and a pullback is common.\n' +
      'In between is neutral. A strong stock can stay overbought for weeks, so treat it as a gauge, not a signal to act.'],
    sma: ['Moving average',
      'The average closing price over the last N days: 20 days is about a month, 50 about 3 months, 200 about a year.\n' +
      'It smooths out day-to-day noise. Price above its average suggests an uptrend; below suggests a downtrend.\n' +
      'When the short average (20) is above the medium one (50), the recent trend is rising.'],
    volume: ['Volume',
      'How many shares changed hands. It matters most compared with normal: well above the 20-day average means unusual interest.\n' +
      'Heavy volume on an up day shows buyers are active; on a down day, sellers are.\n' +
      'The free price feed covers part of the market, so volume here is a sample, not the full total.'],
    rating: ['Technical rating',
      'Each signal (price versus its 20, 50 and 200-day averages, 20 versus 50-day average, RSI, MACD, volume) votes bullish, neutral or bearish.\n' +
      'The rating is how many agree, from Strong Sell to Strong Buy.\n' +
      'It looks only at price history, not the company’s earnings or value, and it is not advice.'],
    trend: ['Trend',
      'Compares today’s price with a moving average (20, 50 or 200 days) and which way that average has been heading.\n' +
      'Up: price above a rising average. Down: below a falling one. Sideways: mixed. Short, medium and long term use 20, 50 and 200 days.'],
    dayrange: ['Day range',
      'Today’s lowest and highest price. The marker shows where the price is now between them: left is near the low, right near the high.'],
    week52: ['52-week range',
      'The lowest and highest price over the past year. The marker shows where the price sits: near the left it is close to its yearly low, near the right close to its yearly high.'],
    change: ['Change',
      'How much the price has moved since the previous close (the last price of the prior trading day).'],
    prevclose: ['Previous close',
      'The last price of the prior trading day. Today’s change is measured from it.'],
    bid: ['Bid',
      'The highest price a buyer is offering right now. If you sell at market you usually get about this.'],
    ask: ['Ask',
      'The lowest price a seller will take right now. If you buy at market you usually pay about this. The gap between bid and ask is the spread: wide spreads (common outside regular hours) cost you more.'],
    earnings: ['Next earnings',
      'The date the company reports its quarterly results. Prices often move sharply that day, in either direction. Funds and ETFs do not report earnings.'],
    vwap: ['VWAP',
      'Volume-weighted average price: the average price paid today, counting busier moments more. Above it, buyers today are ahead; below it, behind.']
  };
  function attr(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;'); }
  window.termAttrs = function (key) {
    var t = window.TERMS[key]; if (!t) { return ''; }
    return ' data-ctip="' + attr(t[0]) + '" data-ctip-note="' + attr(t[1]) + '"';
  };
  // Which term a rating signal's name ("Price vs 50-day average", "RSI (14)", "MACD", "Volume", ...) is about.
  window.termKeyForSignal = function (name) {
    name = String(name || '');
    return /RSI/i.test(name) ? 'rsi' : /MACD/i.test(name) ? 'macd' : /volume/i.test(name) ? 'volume' : /average/i.test(name) ? 'sma' : '';
  };
  window.MACD_HELP = window.TERMS.macd[1];
  window.macdTipAttrs = function (state, cross, ago) {
    var when = ago == null ? '' : ago === 0 ? 'today' : ago === 1 ? 'yesterday' : ago + ' days ago';
    var val = !state ? 'Not enough history yet' : state === 'above' ? 'MACD is above its signal line: momentum rising' : 'MACD is below its signal line: momentum fading';
    var last = cross ? '\nLast crossover: ' + cross + (when ? ', ' + when : '') + '.' : (state ? '\nNo crossover in the history checked.' : '');
    return ' data-ctip="' + attr(window.TERMS.macd[0]) + '" data-ctip-val="' + attr(val) + '"' + (state ? ' data-ctip-color="' + (state === 'above' ? '#1f8a3f' : '#d70015') + '"' : '') +
      ' data-ctip-note="' + attr(window.MACD_HELP + last) + '"';
  };
}
"""
