# tradovate_web_ui_api.py

"""
UI-driven Tradovate adapter implementing my TradingAPIInterface by controlling
the real Tradovate web app in a browser via playwright (no REST keys needed).

First run:
    pip install playwright
    playwright install

Env (example):
    TRADING_PLATFORM=tradovate_ui
    TRADOVATE_USER=you@example.com
    TRADOVATE_PASS=******
    TRADOVATE_BASE_URL=https://trader.tradovate.com
    HEADLESS=0

"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from pathlib import Path
import logging
import os
import time
import re
import json
import asyncio, threading
import traceback, sys

# Import your shared interface
# If our interface name/module differs, we will adjust this import
from api_interface import TradingAPIInterface

from playwright.async_api import async_playwright, Error as PWError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)
logger.info("Loaded tradovate_web_ui_api from: %", __file__)

CLICKABLE = ":is(button, div.btn, [role=button], a[role=button], span.btn)"
TRACE_PRICES = False

class TradovateWebUIAPI(TradingAPIInterface):
    """
    IMPORTANT: Replace the CSS selectors with the real, stable selectros from Tradovate.
    Prefer data-* or aria-* attributes. Avoid brittle class names.
    """

    def __init__(
        self,
        base_url: str = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        headless: bool = False,
        storage_dir: str = ".browser_state",
        timeout_ms: int = 15_000,
        mfa_handler=None, # optional: callable(page) -> None, to complete 2FA manually on first run
        dry_run: bool = True,
        fixture_html_path: str = None,
        manual_login: bool = True,
        ui_confirm: bool | None = None
        ):

        self.base_url = base_url or os.getenv("TRADOVATE_BASE_URL", "https://trader.tradovate.com")
        self.username = username or os.getenv("TRADOVATE_USER", "")
        self.password = password or os.getenv("TRADOVATE_PASS", "")
        self.headless = bool(int(os.getenv("HEADLESS", "0"))) if isinstance(headless, bool) else bool(int(headless))
        self.storage_dir = Path(os.getenv("BROWSER_STATE_DIR", storage_dir))
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.storage_state_file = str(self.storage_dir / "tradovate_auth.json")
        self.timeout_ms = timeout_ms
        self.mfa_handler = mfa_handler
        self.dry_run = dry_run
        # if not given, infer from env/DRY_RUN_UI
        if ui_confirm is None:
            self.ui_confirm = os.getenv("DRY_RUN_UI", "false").lower() == "true"
        else:
            self.ui_confirm = ui_confirm
        self.fixture_html_path = fixture_html_path
        self.browser_mode = os.getenv("BROWSER_MODE", "cdp") # cdp|chrome|webkit|chromium
        self.manual_login = manual_login

        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._connected = False
        self._sel = {}
        self.clickable = CLICKABLE
        self.TRACE_PRICES = TRACE_PRICES
        
        try:
            self._load_selectors()
        except Exception:
            # minimal defaults using your current page hints
            self._sel = {
                 "order.buy_market": [".market-buttons >> text=Buy Mkt"],
                "order.sell_market": [".market-buttons >> text=Sell Mkt"],
                "order.qty_input": [
                    ".info-column-qty input.form-control",
                    ".info-column-qty .select-input input",
                    "xpath=//small[contains(.,'Quantity')]/following::input[1]"
                ],
                "orders.tab": ["ul.lm_tabs .lm_title:has-text('Orders')"],
                "positions.tab": ["ul.lm_tabs .lm_title:has-text('Positions')"],
                "account.balance_pane": [".account-info-inline .balance-view .balance-row"],
                "app.logged_in_marker.any": [
                    ".market-buttons .btn.btn-success",".market-buttons .btn.btn-danger",".last-price-info .number"
                ],
                "symbol.open_search": [".symbol-search-button", "text=Search", "input[placeholder*='Search']"],
                "symbol.search_input": ["input[placeholder*='Search']", "input[type='search']"],
                "symbol.first_result": [".search-list .item, .list .item, .rc-virtual-list-holder-inner .rc-select-item-option-content"]
            }

    # ------------------- TradingAPIInterface: Lifecycle --------------------

    def connect(self) -> bool:
        if getattr(self, "_connected", False):
            return True
        try:
            self._launch()
            self._login_if_needed()
            try:
                txt = self._inner_text_any(".last-price-info .number", timeout=800)
                if not txt:
                    # not fatal, still consider connected - UI scrape will retry
                    pass
            except Exception:
                pass
            self._connected = True
            return True
        except Exception as e:
            self._connected = False
            logger.exception("TradovateWebUIAPI.connect failed: %s", e)
            self._connect_fail("connect", e)
            print("connect() failed:", e, file=sys.stderr)
            traceback.print_exc()
            return False

    def disconnect(self) -> bool:
        try:
            if self._context and os.getenv("BROWSER_MODE", "cdp").lower() != "cdp":
                # Persist session (cookies, localStorage)
                self._run(self._context.storage_state(path=self.storage_state_file))
            if self._browser:
                self._run(self._browser.close())
            if self._pw:
                self._run(self._pw.stop())
            return True
        except Exception:
            return False
        finally:
            self._pw = self._browser = self._context = self._page = None
            self._connected = False

    def is_connected(self) -> bool:
        return bool(self._connected)

    def get_platform_name(self) -> str:
        return "tradovate ui"


    # ------------- TradingAPIInterface: Market Data ----------------

    # def get_current_price(self, symbol: str) -> float:
    #     try:
    #         self._ensure_symbol_loaded(symbol)
    #         last_text = self._inner_text("[data-test-id='last-price']") # REPLACE Selector
    #         return self._to_float(last_text)
    #     except Exception as e:
    #         logger.warning("get_current_price(%s) failed: %s", symbol, e)
    #         return float("nan")

    def get_order_book(self, symbol: str, depth: int = 10) -> Dict[str, Any]:
        try:
            self._ensure_symbol_loaded(symbol)
            bids = self._scrape_ladder("[data-test-id='bid-row']", depth) # REPLACE
            asks = self._scrape_ladder("[data-test-id='ask-row']", depth) # REPLACE
            return {"symbol": symbol, "bids": bids, "asks": asks, "timestapm": datetime.utcnow().isoformat()}
        except Exception as e:
            logger.warning("get_order_book(%s) failed: %s", symbol, e)
            return {"symbol": symbol, "bids": [], "asks": [], "error": str(e)}

    # ------------- TradingAPIInterface: Trading ---------------------

    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict[str, Any]:
        return self._place_order(symbol, side, quantity, order_type="market")

    def place_limit_order(self, symbol: str, side: str, quantity: float, price: float) -> Dict[str, Any]:
        return self._place_order(symbol, side, quantity, order_type="limit", price=price)

    def place_stop_order(self, symbol: str, side: str, quantity: float, stop_price: float) -> Dict[str, Any]:
        # If our interface expects "price" instead of "stop_price", we will be adjusting here 
        return self._place_order(symbol, side, quantity, order_type="limit", price=stop_price)

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        try:
            self._ensure_page()
            self._click("[data-test-id='orders-tab']") # REPLACING
            self._click(f"[data-test-id='cancel-{order_id}']") # REPLACING
            self._maybe_click("[data-test-id='confirm-cancel']", 3000) # REPLACING
            self._wait(f"[data-test-id='order-{order_id}-canceled']", self.timeout_ms) # REPLACING
            return True
        except Exception as e:
            self._snapshot("cancel_order_error")
            logger.warning("cancel_order(%s, %s) failed: %s", symbol, order_id, e)
            return False

    def close_position(self, symbol: str) -> Dict[str, Any]:
        try:
            self._ensure_page()
            self._click("[data-test-id='positions-tab']") # REPLACING
            self._click(f"[data-test-id='closepos-{symbol}']") # REPLACING
            self._maybe_click("[data-test-id='confirm-close']", 3000) # REPLACING
            return {"symbol": symbol, "status": "close_submitted"}
        except Exception as e:
            self._snapshot("close_position_error")
            return {"symbol": symbol, "error": str(e)}


    # ------------- TradingAPIInterface: Portfolio ---------------------

    def get_open_orders(self) -> List[Dict[str, Any]]:
        try:
            self._ensure_page()
            self._click("[data-test-id='orders-tab']") # REPLACING
            rows = self._all("[data-test-id='orders-row']") # REPLACING
            out = []
            for r in rows:
                out.append({
                    "id": r.get_attribute("data-order-id") or "",
                    "symbol": r.get_attribute("data-symbol") or "",
                    "side": (r.get_attribute("data-side") or "").upper(),
                    "type": r.get_attribute("data-type") or "",
                    "qty": self._to_float(r.get_attribute("data-qty")),
                    "price": self._to_float(r.get_attribute("data-price")),
                    "status": r.get_attribute("data-status") or "",
                })
            return out
        except Exception as e:
            logger.warning("get_open_orders failed: %s", e)
            return []

    
    def get_positions(self) -> List[Dict[str, Any]] | None:
        """
        Returns:
        - [] if we are confidently flat (positions table exists but no non-zero NET POS rows)
        - [{symbol, qty, ...}, ...] for ALL rows we can parse (qty may be 0 too, for debugging)
        - None if we cannot determine (UI not found / scrape failed)
        """
        try:
            self._ensure_page()
            self.cleanup_backdrops(timeout_ms=1500)

            # Go to positions tab (using selector map)
            self._click_any("positions.tab", timeout_ms=3000)
            self.cleanup_backdrops(timeout_ms=1500)
            
            # Wait for positions table container (using selector map)
            table_sel = self._wait_any(self._expand("positions.table"), timeout_ms=2500)
            if not table_sel:
                logger.warning("get_positions: positions.table not found/visible")
                return None

            table = self._page.locator(table_sel).first
            logger.info("get_positions: using table selector=%s", table_sel)

            # --- Try a few common patterns inside the table ---

            try:
                empty_markers = [
                    "text=/no positions/i",
                    "text=/flat/i",
                    "text=/you have no positions/i",
                ]
                for em in empty_markers:
                    if self._run(table.locator(em).count(), timeout=0.8):
                        return []
            except Exception:
                pass

            # Better row patterns (virtualised lists / div tables)
            row_candidates = [
                ".fixedDataTableRowLayout_rowWrapper",
                ".public_fixedDataTableRow_main",
                "[class*='fixedDataTableRow']",
                "[role=row]",
                "tbody tr",
                "tr",                                   # classic table rows
                # ".table-row",
                # ".row",                                 # div-table style
                # ".rc-virtual-list-holder-inner > div",  # common virtual list
                # "[data-test-id*='position']",           # if tradovate uses test ids
                # ".position-row",
            ]

            # Cell locators
            cell_candidates = [
                ".public_fixedDataTableCell_cellContent",
                "[class*='Cell_cellContent']",
                ".fixedDataTableCellLayout_main .public_fixedDataTableCell_cellContent",
                "[role=cell]",
                "td"
            ]


            # 5) Helper: what counts as a tradable instrument symbol?
            # Prefer futures-style: ES, NQ, YM, RTY plus optional month code + digit (ESH6).
            sym_re = re.compile(r"\b(?:ES|NQ|YM|RTY|MES|MNQ|MYM|M2K)(?:[FGHJKMNQUVXZ]\d)?\b", re.I)

            # Strong NET POS extractor (handles: "NET POS: 3", "NET POS 0", etc)
            netpos_re = re.compile(r"\bNET\s*POS\b[:\s]*(-?\d+)\b", re.I)

            rows = None
            used_row_sel = None

            # out: list[dict] = []
            for rsel in row_candidates:
                try:
                    loc = table.locator(rsel)
                    cnt = self._run(loc.count(), timeout=1.0) or 0
                    if cnt > 0:
                        rows = loc
                        used_row_sel = rsel
                        break
                except Exception:
                    continue
            
            if rows is None:
                # Table exist but no rows found -> confidently flat
                logger.info("get_positions: table found but no rows matched row locators")
                return []

            logger.info("get_positions: using row selector=%s", used_row_sel)

            out: List[Dict[str, Any]] = []
            cnt = self._run(rows.count(), timeout=1.0) or 0
            max_rows = min(cnt, 100)

            qty_parse_failed = False
            # max_rows = min(cnt, 60)
            for i in range(max_rows):
                r = rows.nth(i)
                try:
                    if not self._run(r.is_visible(), timeout=0.6):
                        continue

                    row_txt = self._run(r.inner_text(), timeout=1.0) or ""
                    row_txt_norm = " ".join(row_txt.split())
                    
                    # Skip empty/headers
                    if not row_txt_norm:
                        continue

                    # Pull cells (preferrred)
                    cells = None
                    used_cell_sel = None
                    cell_texts: List[str] = []
                    for csel in cell_candidates:
                        try:
                            c = r.locator(csel)
                            ccount = self._run(c.count(), timeout=0.6) or 0
                            if ccount > 0:
                                cells = c
                                used_cell_sel = csel
                                break
                        except Exception:
                            continue

                    if cells is not None:
                        ccount = self._run(cells.count(), timeout=0.6) or 0
                        for j in range(min(ccount, 25)):
                            ct = self._run(cells.nth(j).inner_text(), timeout=0.6) or ""
                            ct = " ".join(ct.split())
                            cell_texts.append(ct)

                    # Find symbol (prefer cells; fallback to row text)
                    sym = None
                    if cell_texts:
                        for ct in cell_texts:
                            m = sym_re.search(ct)
                            if m:
                                sym = m.group(0).upper()
                                break

                    if not sym:
                        m = sym_re.search(row_txt_norm)
                        if m:
                            sym = m.group(0).upper()

                    
                    if not sym:
                        continue # not a position row we understand


                    # 2) Extract qty (NET POS)
                    qty: Optional[int] = None

                    # Best: NET POS from row text
                    mnp = netpos_re.search(row_txt_norm)
                    if mnp:
                        try:
                            qty = int(mnp.group(1))
                        except Exception:
                            qty = None

                    # Fallback: if cells look like [Symbol, NetPos, Bought, Sold, ...]
                    if qty is None and cell_texts:
                        # Try to locate the symbol cell index
                        sym_idx = None
                        for idx, ct in enumerate(cell_texts):
                            if ct.upper() == sym:
                                sym_idx = idx
                                break
                        # Common: Symbol is first column, Net Pos is second
                        cand_idxs = []
                        if sym_idx is not None:
                            cand_idxs.append(sym_idx + 1)
                        cand_idxs.append(1) # Typical net pos column
                        for k in cand_idxs:
                            if 0 <= k < len(cell_texts):
                                t = cell_texts[k]
                                if re.fullmatch(r"-?\d+", t):
                                    qty = int(t)
                                    break


                    # Last resort: avoiding price fragments by excluding decimals
                    if qty is None:
                        ints = re.findall(r"(?<!\.)\b-?\d+\b(?!\.)", row_txt_norm)
                        # only accept reasonalble range
                        for s in ints:
                            try:
                                v = int(s)
                            except Exception:
                                continue
                            if abs(v) <= 5000: # guardrail; ES qty won't be 6947
                                qty = v
                                break


                    # Find instrument symbol
                    # m = sym_re.search(t)
                    # if not m:
                    #     continue
                    # sym = m.group(0)

                    # Quantity: try to find a signed or unsigned int near the symbol
                    # Fallback to "first int"
                    # qty_m = re.search(r"\b-?\d+\b", t)
                    # ints = re.findall(r"\b-?\d+\b", t)
                    # filter out "price-like" big ints (e.g. 6947)
                    # small_ints = [x for x in ints if len(x.lstrip("-")) <= 2] # 1 -2 digits
                    # qty = int(small_ints[0]) if small_ints else 0


                    if qty is None:
                        qty_parse_failed = True
                        # # we found a symbol row but couldn't parse NET POS -> NOT confidently flat
                        # logger.warning("get_positions: qty parse failed for sym=%s row=%s", sym, row_txt_norm)
                        # return None
                        qty = 0 # keep row for debugging

                    out.append({
                        "symbol": sym, 
                        "qty": qty,
                        "cells": cell_texts,
                        "row_text": row_txt_norm,
                        "row_cell": used_row_sel,
                        "cell_sel": used_cell_sel,
                        # "raw": t
                    })

                except Exception:
                    continue

            # Confidently flat if we parsed rows but all qty are zero
            nonzero = [r for r in out if int(r.get("qty") or 0) != 0]
            if nonzero:
                return out # return ALL rows; caller filters

            # If we saw symbol rows but couldn't parse qty reliably, state is UNKNOWN (not flat)
            if qty_parse_failed and out:
                # we found a symbol row but couldn't parse NET POS -> NOT confidently flat
                logger.warning("get_positions: qty parse failed for at least one row; returning None (unknown)")
                # Temporary row_text for check purposes
                self.logger.info("PRINTING ROW_TEXT=%s", out[0].get("row_text"))
                return None

            return []

        except Exception as e:
            logger.warning("get_positions failed: %s", e)
            return None

    def get_balance(self) -> Dict[str, Any]:
        """
        Shape matches your other adapters: e.g.
        { "USD": {"free": 12345.0, "locked": 0.0, "total": 12345.0} }
        """
        try:
            self._ensure_page()
            # Equity line in the inline account
            # sel = ".account-info-inline .balance-view .balance-row"
            selectors = [
                ".account-info-inline .balance-view .balance-row",
                ".account-info-inline .balance-row",
                ".balance-row"
            ]

            # attempt to read the inline balance next
            # self._wait_visible_any(".account-info-inline .balance-view .balance-row", self.timeout_ms)
            row_text = None
            deadline = time.time() + 1.0
            while time.time() < deadline and not row_text:
                for sel in selectors:
                    try:
                        txt = self._inner_text_any(sel, timeout_ms=250)
                        if txt and txt.strip():
                            row_text = txt.strip()
                            break
                        # self._wait_visible_any(sel, self.timeout_ms)
                        # row_text = self._inner_text_any(sel, timeout_ms=self.timeout_ms)
                        # if row_text:
                        #     break
                    except Exception:
                        continue

                if not row_text:
                    time.sleep(0.05)
                    # raise ValueError("Balance row exists but has no text")

            # Very simple parse: extract first number-like token
            numbers = re.findall(r"[-+]?\d[\d,]*(?:\.\d+)?", row_text)

            if not numbers:
                raise ValueError("No numeric values in '{row_text}'")

            eq = float(numbers[0].replace(",", "")) if numbers else float("nan")

            if eq == eq:
                self._last_equity = eq

            # Ensure account panel visible
            # REPLACING selectors with the ones found in Tradovate
            # eq = self._to_float(self._inner_text("[data-test-id='cash-balance']"))
            # locked = self._to_float(self._inner_text("[data-test-id='funds-locked']")) # REPLACING
            # total = cash + (locked if locked == locked else 0.0)
            return {"USD": {"free": eq, "locked": 0.0, "total": eq}}
        except Exception as e:
            logger.warning("get_balance failed: %s", e)
            cached = getattr(self, "_last_equity", float("nan"))
            return {"USD": {"free": cached, "locked": 0.0, "total": cached, "error": str(e)}}


    def get_account_info(self) -> Dict[str, Any]:
        try:
            bal = self.get_balance()
            return {"balance": bal, "timestamp": datetime.utcnow().isoformat()}
        except Exception as e:
            return {"error": str(e)}

    
    def get_current_price(self, symbol: str | None = None):
        """
        Return the 'last' price from the chart whose header contains the given symbol.
        If multiple charts are open, this scopes to the correct one.
        Fallbacks:
            - Any chart's .last-price-info .number
            - Your explicit left/right deep selectors (if you want them)
        Returns float | None.   
        """

        def _clean_to_float(txt: str | None):
            if not txt:
                return None
            # Prefer your existing parser
            if hasattr(self, "_parse_price_text"):
                try:
                    v = self._parse_price_text(txt)
                    if v is not None:
                        if getattr(self, "TRACE_PRICES", False):
                            logger.info("get_current_price(%s) -> %s", symbol, v)
                        return v
                except Exception:
                    pass
            # fallback cleaner: digits, dot, minus
            try:
                cleaned = "".join(ch for ch in txt if ch.isdigit() or ch in ".-")
                return float(cleaned) if cleaned else None
            except Exception:
                return None
        
        try:
            sels: list[str] = []
            if symbol:
                sels += [
                    f".module.chart:has(.header:has-text('{symbol}')) .last-price-info .number",
                    f".chart-wrapper:has(.header:has-text('{symbol}')) .last-price-info .number",
                ]
            # add mapping from your selector file
            try:
                if hasattr(self, "_sel"):
                    mapping = self._sel.get("price.last")
                    if mapping:
                        sels.extend(mapping if isinstance(mapping, list) else [mapping])       
            except Exception:
                pass

            sels += [
                ".last-price-info .number",
                "div.info-column.last-price-info .number",
            ]
            
            # Try each selector on page or any frame
            for sel in sels:
                try:
                    txt = self._inner_text_any(sel, timeout_ms=1200)
                    val = _clean_to_float(txt)
                    if val is not None:
                        if getattr(self, "TRACE_PRICES", False):
                            logger.info("get_current_price(%s) -> %s", symbol, val)
                        return val
                except Exception:
                    continue


            # 3) Final fallback: Our explicit left/right deep selectors from our capture
            deep_candidates = [
                # LEFT CHART deep path provided
                "#content > div > div.app-modules > div > div.gm-scroll-view > div > div > div > div.lm_item.lm_column > div:nth-child(1) > div:nth-child(1) > div.lm_items > div:nth-child(1) > div > div > div.module.chart.chart-wrapper > div.header > div > div > div.gm-scroll-view > div.info-column.last-price-info > div.number.text-success",
                # RIGHT CHART deep path provided
                "#content > div > div.app-modules > div > div.gm-scroll-view > div > div > div > div.lm_item.lm_column > div:nth-child(1) > div:nth-child(3) > div.lm_items > div:nth-child(1) > div > div > div.module.chart.chart-wrapper > div.header > div > div > div.gm-scroll-view > div.info-column.last-price-info > div.number.text-success",
            ]

            # 2) Fallback: any visible chart 'Last' price (first one found)
            # try:
            #     # Use selector map if present
            #     if hasattr(self, "_sel") and "price.last_any" in self._sel:
            #         for sel in self._expand("price.last_any"):
            #             loc = self._page.locator(sel).first
            #             price_text = self._run(loc.inner_text(timeout=2000))
            #             val = self._parse_price_text(price_text)
            #             if val is not None:
            #                 return val
            # except Exception:
            #     pass

            for sel in deep_candidates:
                try:
                    # txt = self._run(self._page.locator(sel).first.inner_text(timeout=1500))
                    txt = self._inner_text_any(sel, timeout_ms=1500)
                    val = _clean_to_float(txt)
                    # price_text = self._run(loc.inner_text(timeout=1500))
                    # val = self._parse_price_text(price_text)
                    if val is not None:
                        if getattr(self, "TRACE_PRICES", False):
                            logger.info("get_current_price(%s) -> %s", symbol, val)
                        return val
                except Exception:
                    continue

            return None
    
        except Exception as e:
            try:
                if hasattr(self, "logger"):
                    self.logger.warning(f"get_current_price({symbol}) failed: {e}")
            except Exception:
                pass
            logger.debug("get_current_price(%s) -> None (no selector matched)", symbol)
            return None


    def _parse_price_text(self, text: str | None):
        """
        Normalize price settings like '113 140' or '6,675.00' -> float
        """
        if not text:
            return None
        # remove spaces used as thousands separators
        t = text.replace(" ", "")
        # If UI uses commas for thousands and dot for decimal, this works naturally
        # If UI uses comma as decimal separator, we could tweak here
        try:
            return float(t.replace(",", "")) # '6,675.00' -> 6675.00
        except ValueError:
            # Try European format e.g. '6.675,00' -> 6675.00
            try:
                t2 = t.replace(".", "").replace(",", ".")
                return float(t2)
            except Exception:
                return None




    # -------------------------- Internals -----------------------------

    def _load_selectors(self):
        import json, os
        path = os.getenv("TV_SELECTORS", "tradovate_selectors.json")
        with open(path, "r") as f:
            self._sel = json.load(f)


    def S(self, key):
        val = self._sel.get(key)
        if val is None: raise KeyError(f"Missing selector for {key}")
        return val if isinstance(val, list) else [val]

    def _place_order(self, symbol: str, side: str, quantity: float, order_type: str, price: Optional[float] = None) -> Dict[str, Any]:
        try:
            logger.info(
                "_place_order: symbol=%s side=%s qty=%s type=%s price=%s dry_run=%s ui_confirm=%s",
                symbol,
                side,
                quantity,
                order_type,
                price,
                self.dry_run,
                getattr(self, "ui_confirm", False)
            )
            # Clear any stale modals/backdrops before starting a new ticket
            self._pre_click_hygiene()

            # Ensure the correct symbol tile is active
            self._ensure_symbol_loaded(symbol)

            # SAFETY GATE: prevent stacking if positions are unknown or non-flat
            try:
                pos = self.get_positions()
            except Exception:
                pos = None

            if pos is None:
                logger.warning("_place_order: Positions unknown/undeterminable — blocking order to avoid stacking.")
                return {"error": "positions_unknown_block", "symbol": symbol, "side": side, "qty": quantity, "type": order_type, "price": price}
            
            # Quantity
            filled = self.set_quantity(quantity)
            # filled = self._fill_quantity(quantity)
            if not filled:
                raise RuntimeError("Could not locate/fill Quantity input")

            # optional strict mode: only allow when flat
            if len(pos) > 0:
                logger.warning("_place_order: Existing position(s) detected — blocking to avoid stacking. pos=%s", pos)
                return {"error": "position_not_flat_block", "positions": pos, "symbol": symbol, "side": side, "qty": quantity, "type": order_type, "price": price}

            # Select side
            if side.upper() == "BUY":
                logger.info("_place_order: clicking Buy Mkt (order.buy_market)")
                # self._click_any(".market-buttons >> text=Buy Mkt", timeout_ms=self.timeout_ms)
                self._click_any("order.buy_market", timeout_ms=self.timeout_ms)
            else:
                logger.info("_place_order: clicking Sell Mkt (order.sell_market)")
                # self._click_any(".market-buttons >> text=Sell Mkt", timeout_ms=self.timeout_ms)
                self._click_any("order.sell_market", timeout_ms=self.timeout_ms)
            # self._click(f"[data-test-id='ticket-side-{side.lower()}']") # REPLACING

            if order_type.lower() in ("limit", "stop"):
                if price is None:
                    raise ValueError("price/stop required for limit/stop")
                logger.info("_place_order: filling price field with %s", price)
                # For stop orders, this might be a different field - adjust selector
                # self._page.get_by_placeholder("price").fill(str(price))
                # self._fill("[data-test-id='ticket-price']", str(price)) # REPLACING
                self._fill_any(
                    "[placeholder*='price'], input[aria-label*='Price'] input[name*='price']",
                    str(price),
                )

            # DRY RUN: Dont submit; just snapshot & return a fake id
            if self.dry_run:
                try:
                    if getattr(self, "ui_confirm", False):
                        logger.info("_place_order: dry_run+ui_confirm -> confirm_order()")
                        # the JSON has separate selectors for buy/sell
                        # if side.upper() == "BUY":
                            # logger.info("UI confirm enabled, clicking %s", "confirm.submit_buy" if side.upper()=="BUY" else "confirm.submit_sell")
                            # self._maybe_click("confirm.submit_buy", 2000)
                        self.confirm_order(side=side, timeout_ms=3000)
                        # else:
                            # self._maybe_click("confirm.submit_sell", 2000)
                            # self.confirm_order(side=side, timeout_ms=2000)
                except Exception as e:
                    logger.warning(
                        "_place_order: dry_run confirm_order failed: %s", e
                    )
                    # don't break dry-run for a missing modal
                    # pass
                self._snapshot(f"dry_run_{side.lower()}_{order_type.lower()}")
                return {
                    "orderId": "DRYRUN-" + datetime.utcnow().strftime("%H%M%S"),
                    "symbol": symbol,
                    "side": side.upper(),
                    "qty":quantity,
                    "type": order_type.upper(),
                    "price": price,
                    "status": "dry_run_only"
                }
            logger.info("_place_order: calling confirm_order() for real submit")
            # Real submit (when we are ready)
            # try real primary buttons first
            # if not self._maybe_click("confirm.submit_buy", 1200) and not self._maybe_click("confirm.submit_sell", 1200):
            if not self.confirm_order(side=side, timeout_ms=self.timeout_ms):
                # fallback to generic names
                # for sel in ["button:has-text('Send')", "button:has-text('Submit')", ".modal-dialog .btn.btn-primary"]:
                    # if self._maybe_click(sel, 800):
                    #     break
                raise RuntimeError("Failed to find/press confirm button in Tradovate modal")

            # self._page.get_by_text("Submit").click()

            # try the JSON confirm selectors first
            # if side.upper() == "BUY":
            #     self._maybe_click("confirm.submit_buy", 3000)
            # else:
            #     self._maybe_click("confirm.submit_sell", 3000)
            # # fallback to generic text confirm
            # self._maybe_click("text=Confirm", 3000)
            try:
                self._wait("text=Order Submitted", self.timeout_ms) # To replace with an actual success marker
                logger.info("_place_order: 'Order Submitted' toast detected")
            except Exception:
                logger.info(
                    "_place_order: did not see 'Order Submitted' toast, "
                    "but confirm click already attempted"
                )
                # pass

            # TODO: scrape order id from success toast/modal if available
            return {
                    "orderId": f"ORDER-{int(time.time())}",
                    "symbol": symbol,
                    "side": side.upper(),
                    "qty":quantity,
                    "type": order_type.upper(),
                    "price": price,
                    "status": "submitted",
                }

            # Submit and confirm
            # self._click("[data-test-id='ticket-submit']") # REPLACING
            # self._maybe_click("[data-test-id='confirm-submit']", 3000)# REPLACING

            # # Wait for success + capture order id
            # self._wait("[data-test-id='order-success']", self.timeout_ms) # REPLACING
            # order_id = self._attr("[data-test-id='order-success']", "data-order-id") or ""

            # return {
            #     "orderId": order_id,
            #     "symbol": symbol,
            #     "side": side.upper(),
            #     "qty": quantity,
            #     "type": order_type.upper(),
            #     "price": price,
            #     "status": "submitted",
            # }
        except Exception as e:
            self._snapshot("place_order_error")
            logger.exception("_place_order failed: %s", e)
            return {"error": str(e), "symbol": symbol, "side": side, "qty": quantity, "type": order_type, "price": price}


    def _launch(self):
        """
        Launch browser/page using Playwright **async** API on our private loop.
        Supports modes: 'cdp, 'chrome', 'webkit', default chromium.
        Respects: self.headless (bool), self.base_url (str),
                  self.storage_state_file (path or None), self._chromium_args() optional.      
        """
        self._ensure_loop()
        headless = bool(getattr(self, "headless", False))
        base_url = getattr(self, "base_url", "https://trader.tradovate.com/")
        storage_state_file = getattr(self, "storage_state_file", None)
        mode = (os.getenv("PW_MODE") or os.getenv("BROWSER_MODE") or "cdp").strip().lower()
        args_fn = getattr(self, "_chromium_args", None)

        async def _do_launch():
            # start Playwright
            self._pw = await async_playwright().start()

            # self.browser = await self._pw_chromium.launc(
            #     headless=not getattr(self, "headful", True),
            #     args=getattr(self, "_chromium_args", lambda: [])()
            # )
            # # reuse/open context
            # if getattr(self, "_context", None) is None:
            #     self._context = await self._browser.new_context()
            # self._page = await self._context.new_page()
            # await self._page.goto(self.base_url)

            if mode == "cdp":
                # Connect to the Chrome we started manually
                endpoint = os.getenv("CDP_URL", "http://localhost:9222")
                self._browser = await self._pw.chromium.connect_over_cdp(endpoint)
                # Reusing existing default context or creating one
                if self._browser.contexts:
                    self._context = self._browser.contexts[0]
                else:
                    self._context = await self._browser.new_context(storage_state=storage_state_file) if storage_state_file else await self._browser.new_context()
                self._page = await self._context.new_page()
                await self._page.goto(base_url)
                return
        
            if mode == "chrome":
                # Use system-installed Chrome (no bundled download)
                launch_kwargs = dict(channel="chrome", headless=headless)
                if callable(args_fn):
                    launch_kwargs["args"] = args_fn()
                self._browser = await self._pw.chromium.launch(**launch_kwargs) # Before: channel="chrome", headless=self.headless
                self._context = await self._browser.new_context(storage_state=storage_state_file) if storage_state_file else await self._browser.new_context()
                self._page = await self._context.new_page()
                await self._page.goto(base_url)
                return

            if mode =="webkit":
                # Safari/Webkit (often works on older macOS)
                self._browser = await self._pw.webkit.launch(headless=self.headless)
                self._context = await self._browser.new_context(storage_state=storage_state_file) if storage_state_file else await self._browser.new_context()
                self._page = await self._context.new_page()
                await self._page.goto(base_url)
                return

            # Default: bundled Chromium
            launch_kwargs = dict(headless=headless)
            if callable(args_fn):
                launch_kwargs["args"] = args_fn()
            self._browser = await self._pw.chromium.launch(**launch_kwargs)
            self._context = await self._browser.new_context(storage_state=storage_state_file) if storage_state_file else await self._browser.new_context()
            self._page = await self._context.new_page()
            await self._page.goto(base_url)
        
        self._run(_do_launch(), timeout=120)



        # Fallback (bundled Chromium; likely unsupported on macOS 10.15, but keep for completeness)
        # self._browser = self._pw.chromium.launch(headless=self.headless)
        # if os.path.exists(self.storage_state_file):
        #     self._context = self._browser.new_context(storage_state=self.storage_state_file)
        # else:
        #     self._context = self._browser.new_context()
        # self._page = self._context.new_page()

    def _login_if_needed(self):
        # Load local fixture, if any
        # Load a local DOM snapshot for offline tests, if provided
        # 3) Building robust set of login-success markers
        # If we're already logged in, detect something stable in the top bar
        markers = [
            # buy/sell group visible when logged in
            ".market-buttons .btn.btn-success",        # visible tab text when logged in
            ".market-buttons .btn.btn-danger",
            # orders/positions tabs visible in the module layout
            "ul.lm_tabs .lm_title:has-text('Orders')",  # buy mkt strip variable
            "ul.lm_tabs .lm_title:has-text('Positions')",
            ".account-info-inline .balance-view .balance-row"
            # balance widgets (cash/equity)
            # "[data-test-id='cash-balance']",
            ".account-selector-wrapper",               # account widget
            # price widget in chart header
            ".last-price-info .number"
            # "text=Orders",
        ]
        user_marker = os.getenv("LOGIN_MARKER")
        if user_marker:
            markers.insert(0, user_marker)

        # 1) If a local HTML fixture is et, just open it.
        if getattr(self, "fixture_html_path", None):
        # if self.fixture_html_path:
            self._run(self._page.goto(f"file://{os.path.abspath(self.fixture_html_path)}"))
            # We are "connected" to a static DOM, skip real login
            return

        # Normal login real site
        # 2) Go to base_url on the current page if not already
        try:
            # If we already on any logged-in page/frame, skip navigation entirely
            pg = self._find_logged_in_page(markers)
            if pg:
                self._page = pg
                return
            # otherwise trying to base_url once
            self._run(self._page.goto(self.base_url, wait_until="domcontentloaded"))
        except Exception:
            # In CDP mode we might already be on the app page; ignoring navigation errors
            pass

        # If already logged in on any page/frame, return immediately
        pg = self._find_logged_in_page(markers)
        if pg:
            self._page = pg
            return

        # If manual_login: let the user log_in, then wait for a logged-in marker
        if self.manual_login:
            # Give you time to type; we just wait.
            print("Please log in manually in the opened browser window...")

            # 4) Try for up to ~120s; if we find a page/frame a with any marker, switch self._page to it
            # marker = None
            deadline = time.monotonic() + 120 #(self.timeout_ms * 6 / 1000.0)
            while time.monotonic() < deadline:
                pg = self._find_logged_in_page(markers)
                if pg:
                    self._page = pg
                    # Persist session when on CDP
                    if getattr(self, "browser_mode", os.getenv("BROWSER_MODE", "cdp")) != "cdp":
                        self._run(self._context.storage_state(path=self.storage_state_file))
                    return
                time.sleep(0.2)

        # last_error = None

        # while time.monotonic() < deadline: # and marker is None:
        #     for sel in logged_in_markers:
        #         try:
        #             self._wait_visible_any(sel, 1000)
        #             marker = sel
        #             break
        #         except Exception:
        #             continue
        # if not marker:
            raise RuntimeError("Manual login timed out - no logged-in marker found.")
        else:
            # OPTIONAL: auto-login path (only if you really want to)
            # Auto-login path (only if you set manual_login=False later
            login_field_candidates = [
                "input[name='username']",
                "input[name='email']",
                "input[type='email']",
                "input[placeholder*='Email']",
                "input[placeholder*='E-mail']",
                "input[placeholder*='Username']"
            ]

            pwd_field_candidates = [
                "input[name='password']",
                "input[type='password']",
                "input[placeholder*='Password']"
            ]

            user_sel = self._wait_any(login_field_candidates, timeout_ms=self.timeout_ms)
            if not user_sel:
                raise RuntimeError("Login form not found (no username/email field visible).")

            self._fill(user_sel, self.username)

            pwd_sel = self._wait_any(pwd_field_candidates, timeout_ms=self.timeout_ms)
            if not pwd_sel:
                raise RuntimeError("Login form not found (no password field visible).")

            self._fill(pwd_sel, self.password)
            submit_candidates = [
                "button[type='submit']",
                "button:has-text('Log in')",
                "button:has-text('Login')",
                "text=Sign in"
            ]

            btn = self._wait_any(submit_candidates, timeout_ms=2000)
            if btn:
                self._click(btn)
            else:
                self._run(self._page.keyboard.press("Enter"))
            # waiting for logged-in marker
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                pg = self._find_logged_in_page(markers)
                if pg:
                    self._page = pg
                    # Persist session when on CDP
                    if getattr(self, "browser_mode", os.getenv("BROWSER_MODE", "cdp")) != "cdp":
                        self._run(self._context.storage_state(path=self.storage_state_file))
                    return
                time.sleep(0.2)
            raise RuntimeError("Login did not complete - logged-in marker not found.")


    def _find_logged_in_page(self, markers: list[str]):
        """
        Search across all pages and frames for any 'logged-in' marker.
        Return the page that contains it, or None.
        """
        # Refresh page list (CDP mode may have multiple tabs)
        try:
            pages = list(self._context.pages) if self._context else ([self._page] if self._page else []) # safe in async via property
        except Exception:
            pages = [self._page] if self._page else []

        for pg in pages:
            if self._any_visible_global(pg, markers, per_attempt_ms=400):
                return pg
        return None


    def _any_visible_global(self, page, selectors, per_attempt_ms=400) -> bool:
        sels = selectors if isinstance(selectors, (list, tuple)) else [selectors]
        # check main page first
        for sel in sels:
            try:
                self._run(page.wait_for_selector(sel, timeout=per_attempt_ms, state="visible"), timeout=per_attempt_ms/1000 + 5)
                return True
            except Exception:
                pass
        # then every frame
        try:
            frames = list(page.frames)
        except Exception:
            frames = []
        for fr in frames:
            for sel in sels:
                try:
                    self._run(fr.wait_for_selector(sel, timeout=per_attempt_ms, state="visible"), timeout=per_attempt_ms/1000 + 5)
                    return True
                except Exception:
                    pass
        return False


    def _ensure_page(self):
        if not self._page:
            raise RuntimeError("Browser page is not initialised")

    
    def _ensure_symbol_loaded(self, symbol: str):
        self._click_any("symbol.open_search")
        try:
            self._fill_first("symbol.search_input", symbol)
            self._wait_any("symbol.first_result")
            self._click_any("symbol.first_result")
        except Exception:
            pass
        
        self._wait_any("order.buy_market", timeout=self.timeout_ms)
        # self._page_locator(".market-buttons").first().wait_for(timeout=self.timeout_ms) # REPLACING
        return True

    def ensure_symbol_loaded(self, symbol: str) -> bool:
        """
        Best-effort: ensure the active chart shows the requested symbol.
        Order attempts:
         1) Fast path via our private selectopr-driven _ensure_symbol_loaded
         2) Verify in the chart header
         3) Heuristic symbol search field type + Enter
        Always returns True (non-fatal) so the bot keeps running even if we can't confirm.
        """
        try:
            if not symbol: 
                return True

            # 1) Use your existing selector-driven method if available
            try:
                if hasattr(self, "_ensure_symbol_loaded"):
                    self._ensure_symbol_loaded(symbol) # your current implementation
            except Exception:
                # non-fatal, continue with verification/heuristics
                pass
            # 2) Verify chart header contains symbol (fast check)
            try:
                chart = self._page.locator(f".chart-wrapper:has(.header:has-text('{symbol}'))")
                cnt = self._run(chart.count(), timeout=1.5)
                if cnt and cnt > 0:
                    return True
            except Exception:
                pass

            # 3) Heuriostic: try a few generic symbol search inputs
            search_candidates = [
                "input[placeholder*='Symbol']",
                "input[aria-label*='Symbol']",
                ".symbol-search input",
                "input[type='search']",
            ]
            for sel in search_candidates:
                try:
                    self._run(self._page.wait_for_selector(sel, timeout=800, state="visible"), timeout=1.2)
                    loc = self._page.locator(sel).first
                    try:
                        self._run(loc.fill(""), timeout=0.8)
                    except Exception:
                        pass
                    self._run(loc.type(symbol), timeout=1.2)
                    self._run(self._page.keyboard.press("Enter"), timeout=0.8)
                    # brief settle and re-check
                    time.sleep(0.3)
                    chart2 = self._page.locator(f".chart-wrapper:has(.header:has-text('{symbol}'))")
                    cnt2 = self._run(chart2.count(), timeout=1.5)
                    if cnt2 and cnt2 > 0:
                        return True
                except Exception:
                    continue

            # Couldn't confirm, but don't block trading loop
            return True
        except Exception:
            return True

    def _ensure_loop(self):
        """Start a private asyncio loop on a background thread for Playwright async API."""
        if getattr(self, "_loop", None):
            return
        self._loop = asyncio.new_event_loop()
        self._loop_ready = threading.Event()

        def _runner():
            asyncio.set_event_loop(self._loop)
            self._loop_ready.set()
            self._loop.run_forever()

        self._loop_thread = threading.Thread(target=_runner, daemon=True)
        self._loop_thread.start()
        self._loop_ready.wait()


    def _run(self, coro, timeout=None):
        """Run a coroutine safely on the private loop and return its results"""
        if not getattr(self, "_loop", None):
            self._ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=timeout)


    def set_quantity(self, qty: int | float) -> bool:
        return self._fill_quantity(qty)
        # return bool(self._fill_first("order.qty_input", qty))


    # def place_market_order(self, symbol, side, qty):
    #     self.ensure_symbol_loaded(symbol)
    #     self.set_quantity(qty)
    #     if os.getenv("DRY_RUN", "true").lower() == "true":
    #         return {"dry_run": True, "symbol": symbol, "side": side, "qty": qty}
    #     self._click_any("order.buy_market" if side.upper()=="BUY" else "order.sell_market")
    #     # If confirm appears:
    #     try:
    #         self._wait_any("confirm.modal", timeout=1500)
    #         if side.upper() == "BUY":
    #             self._click_any("confirm.submit_buy")
    #         else:
    #             self._click_any("confirm.submit_sell")
    #     except Exception:
    #         pass

    def click_market_button(self, side: str, symbol: str | None = None, timeout=None, timeout_ms=None, skip_position_checks: bool = False) -> bool:
        """
        Click the Buy Mkt / Sell Mkt button.
        In DRY_RUN we *do not* click any confirm sunbmit
        """
        try:
            side = (side or "").strip().lower()
            buy = side.startswith("b")
            t_ms = self._norm_timeout_ms(timeout=timeout, timeout_ms=timeout_ms, default_ms=getattr(self, "timeout_ms", 3000))

            try:
                target = "Buy" if buy else "Sell"
                # If popover already open, do NOT click outer button again.
                existing = self._run(self._find_confirm_popover(target=target, max_wait_ms=1), timeout=0.5)
                if existing is not None:
                    logger.info("[click_market_button] confirm popover already open (%s); skipping outer click", target)
                    return True # let confirm_order() handle it
            except Exception:
                pass
            
            if not skip_position_checks:
                # SAFETY GATE: prevent stacking if positions are unknown
                try:
                    pos = self.get_positions()
                except Exception:
                    pos = None

                if pos is None:
                    logger.warning("[click_market_button] Positions unknown - blocking click to avoid stacking.")
                    return False

                # Optional: block if any open positions exists
                if len(pos) > 0:
                    logger.warning("[click_market_button] Existing position(s) detected - blocking.")
                    return False

            # Clear any modal/backdrop that could intercept the click
            self._pre_click_hygiene()
            # typical selectors on Tradovate header group; keeping both variants

            # prefer the module that actually shows our symbol in its header
            scoped_container = self._page.locator(
                "#content .module.module-dom:has(.contract-horizontal-info "
                ".info-column.info-column-symbol:has-text('%s'))" % symbol
            )

            btn_scoped = scoped_container.locator(
                ".market-buttons-wrapper .btn.btn-success" if buy else ".market-buttons-wrapper .btn.btn-danger"
                ).filter(has_not=self._page.locator(".modal-dialog"))

            cnt = 0
            try:
                cnt = self._run(btn_scoped.count(), timeout=1.0) or 0
            except Exception:
                cnt = 0


            if cnt > 0:
                btn = btn_scoped.first
            else:
                candidates = [
                    "#content .module.module-dom .header .market-buttons-wrapper "
                    ".btn.btn-success" if buy else
                    "#content .module.module-dom .header .market-buttons-wrapper .btn.btn-danger",


                    ".contract-horizontal-info ~ .market-buttons-wrapper .btn.btn-success" if buy else
                    ".contract-horizontal-info ~ .market-buttons-wrapper .btn.btn-danger",


                    # chart module header (kept from your version)
                    ".module.chart .market-buttons .btn.btn-success" if buy else
                    ".module.chart .market-buttons .btn.btn-danger",
                    ".chart-wrapper .market-buttons-wrapper .btn.btn-success" if buy else
                    ".chart-wrapper .market-buttons-wrapper .btn.btn-danger",
                ]

                # candidates = [
                #     ".market-buttons .btn.btn-success" if buy else ".market-buttons .btn.btn-danger",
                #     "div.market-buttons-wrapper .btn.btn-success" if buy else "div.market-buttons-wrapper .btn.btn-danger",
                # ]

                # Try in order
                # Waiting for the first that is visible
                sel = self._wait_any(candidates, timeout_ms=t_ms)
                if not sel:
                    return False

                btn = self._page.locator(sel).first

            # 3) Click sequence: bring to view, ensure visible & enabled, click
            try:
                self._run(btn.scroll_into_view_if_needed(), timeout=min(1.5, t_ms/1000.0))
            except Exception:
                pass

            try:
                self._run(btn.wait_for(state="visible"), timeout=min(1.5, t_ms/1000.0))
            except Exception:
                pass

            # try normal click, then DOM click, then force click as last resort
            try:
                self._run(btn.click(), timeout=min(2.0, t_ms/1000.0) + 0.5)
                return True
            except Exception:
                try:
                    # sometimes an overlay steals the event; dispatch from DOM
                    btn.evaluate("el => el.click()")
                    return True
                except Exception:
                    # try:
                    self._run(btn.click(force=True), timeout=1.5)
                # Fallback: a backdrop or overlay might still be intercepting -> force
                # self._run(btn.click(force=True), timeout=1.5)
            
                    return True
        except Exception:
            return False

    def confirm_order(self, side: str | None = None, timeout_ms: int = 3000) -> bool:
        """
        PUBLIC sync wrapper used by the bot.
        Internally delegates to async _confirm_order_impl, executed
        on the Playwright event loop via _run.
        """
        try:
            return bool(self._run(self._confirm_order_impl(side=side, timeout_ms=timeout_ms)))
        except Exception as e:
            logger.exception("[confirm_order] wrapper failed: %s", e)
            return False
        finally:
            self.cleanup_backdrops(timeout_ms=1500)


    async def _cleanup_backdrops(self, timeout_ms: int = 1500):
        page = self._page
        # Try Esc first (cheap + often works)
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass

        backdrop = page.locator("#placeholder-for-modals .modal-backdrop.in, .modal-backdrop.in")
        try:
            if await backdrop.count() > 0:
                await backdrop.first.wait_for(state="hidden", timeout=timeout_ms)
        except Exception:
            # last resort: click somewhere safe to dismiss
            try:
                await page.mouse.click(5, 5)
            except Exception:
                pass

    def cleanup_backdrops(self, timeout_ms: int = 1500) -> None:
        # "Sync-safe wrapper for async backdrop cleanup."
        try:
            self._run(self._cleanup_backdrops(timeout_ms=timeout_ms), timeout=(timeout_ms/1000.0 + 1.0))
        except Exception:
            pass


    async def _confirm_order_impl(self, side: str | None = None, timeout_ms: int = 3000) -> bool:
        """
        Confirm an order in the Tradovate UI.


        Rules:
        - Only accept success if we find a dialog with a Buy/Sell button (matching `side`)
            AND that dialog disappears (hidden/detached) after the click.
        - Do NOT treat 'Send' as a confirmation anymore.
        - Support BOTH confirmation styles:
            A) popover/tooltip confirmation (contains "Do not show again")
            B) classic modal-dialog / role=dialog confirmation (Buy/Sell + Cancel)
        """
        side_norm = (side or "").strip().lower()
        page = self._page
        t_ms = int(timeout_ms or getattr(self, "timeout_ms", 3000))

        # CLICKABLE = ":is(button, div.btn, [role=button], a[role=button], span.btn)"

        logger.info(
            "[confirm_order] Attempting UI confirm for side=%s timeout=%sms",
            side_norm.upper() if side_norm else "UNKNOWN",
            timeout_ms,
        )

        def want_buy() -> bool:
            return side_norm.startswith("b")

        def want_sell() -> bool:
            return side_norm.startswith("s")

        target = "Buy" if want_buy() else ("Sell" if want_sell() else None)
        if not target:
            logger.warning("[confirm_order] Unknown side=%r; refusing to click", side)
            return False

        def _all_contexts():
            # include main page + child frames
            return [page] + list(page.frames)

        async def _find_confirm_modal_any(max_wait_ms: int):
            deadline = time.time() + (max_wait_ms / 1000.0)
            modal_selectors = (
                "#placeholder-for-modals .modal-dialog, "
                ".modal-dialog, "
                "[role='dialog'], "
                ".tv-modal, "
                ".dialog"
            )

            while time.time() < deadline:
                for ctx in _all_contexts():
                    try:
                        modals = ctx.locator(modal_selectors)
                        mcount = await modals.count()
                    except Exception:
                        continue

                    for i in reversed(range(mcount)):
                        m = modals.nth(i)
                        try:
                            if not await m.is_visible():
                                continue
                        except Exception:
                            continue

                        try:
                            # must have BOTH cancel and the side button
                            if await m.locator(self.clickable, has_text=re.compile(r"^Cancel$", re.I)).count() == 0:
                                continue
                            if await m.locator(self.clickable, has_text=re.compile(rf"^{target}$", re.I)).count() == 0:
                                continue
                        except Exception:
                            continue

                        return m

                await page.wait_for_timeout(50)

            return None


        logger.info("[confirm_order] Attempting UI confirm for side=%s timeout=%sms", target.upper(), t_ms)

        async def wait_gone(container) -> bool:
            # accept either detached or hidden
            try:
                await container.wait_for(state="detached", timeout=t_ms)
                return True
            except PlaywrightTimeoutError:
                pass
            try:
                await container.wait_for(state="hidden", timeout=750)
                return True
            except PlaywrightTimeoutError:
                return False

        async def safe_click(locator, label: str) -> bool:
            # Try normal click first, than force click as fallback.
            try:
                await locator.scroll_into_view_if_needed(timeout=min(t_ms, 1500))
            except Exception:
                pass
            
            # 1) normal click
            try:
                await locator.click(timeout=t_ms, force=False)
                logger.info(
                    "[confirm_order] clicked '%s' (force=False)", label
                )
                return True
            except Exception as e:
                logger.warning("[confirm_order] click '%s' force=False failed: %s", label, e)
            
            # 2) force fallback
            try:
                await locator.click(timeout=t_ms, force=True)
                logger.info("[confirm_order] clicked '%s' (force=True)", label)
                return True
            except Exception as e:
                logger.warning("[confirm_order] click '%s' force=True failed: %s", label, e)
                return False


        # -------- helper: debug dump visible buttons --------
        async def dump_visible_clickables(where: str):
            try:
                loc = page.locator(":is(button,a,[role=button],div.btn,span.btn)")
                n = await loc.count()
                vis = []
                for i in range(min(n, 80)):
                    el = loc.nth(i)
                    try:
                        if not await el.is_visible():
                            continue
                        txt = (await el.inner_text()).strip()
                        if txt:
                            vis.append(" ".join(txt.split()))
                    except Exception:
                        continue
                logger.info("[confirm_order] %s; visible clickables: %r", where, vis)
            except Exception as e:
                logger.warning("[confirm_order] global button dump failed: %s", e)
        

        # ======================================================================
        # A) POPOVER / TOOLTIP confirmation path (anchor on "Do not show again")
        # ======================================================================
        try:
           
            pop = await self._find_confirm_popover(target=target, max_wait_ms=min(2000, t_ms))
            # if pop is not None:
            #     best = pop

            # # best = None
            # for i in reversed(range(pcount)): # newest/top-most often last
            #     p = popovers.nth(i)
            #     try:
            #         if not await p.is_visible():
            #             continue
            #     except Exception:
            #         continue
                
            #     # Must look like the confirmation popover
            #     # - contains MKT? title
            #     # - contains Do not show again
            #     # - contains Cancel
            #     # - contains the correct confirm side (Buy/Sell)
            #     if await p.locator("text=/MKT\\?/i").count() == 0:
            #         continue
            #     if await p.locator("small", has_text=re.compile("Do not show again", re.I)).count() == 0:
            #         continue
            #     if await p.locator("div.btn.btn-default", has_text=re.compile(r"^Cancel$", re.I)).count() == 0:
            #         continue
            #     if await p.locator("div.btn.btn-success", has_text=re.compile(rf"^{target}$", re.I)).count() == 0:
            #         continue
            #     best = p
            #     break

            if pop is not None:
                logger.info("[confirm_order] using POPOVER confirmation (target=%s)", target)

                # confirm_btn = pop.locator("div.btn.btn-success", has_text=re.compile(rf"^{target}$", re.I)).first
                confirm_btn = pop.locator(self.clickable, has_text=re.compile(rf"^{target}$", re.I)).first
                

                if not await safe_click(confirm_btn, target):
                    # try cleanup
                    try:
                        await page.keyboard.press("Escape")
                    except Exception:
                        pass
                    cancel_btn = pop.locator("div.btn.btn-default", has_text=re.compile(r"^Cancel$", re.I)).first
                    await safe_click(cancel_btn, "Cancel")
                    return False
                # return await click_and_verify(btn, best, target)

                gone = await wait_gone(pop)
                if gone:
                    return True

                # If it didn't disappear, attempt cleanup to avoid stacking
                logger.warning("[confirm_order] popover still visible after clicking '%s'; attempting cleanup", target)
                try:
                    await page.keyboard.press("Escape")
                except Exception:
                    pass
                cancel_btn = pop.locator("div.btn.btn-default", has_text=re.compile(r"^Cancel$", re.I)).first
                await safe_click(cancel_btn, "Cancel")
                await wait_gone(pop)
                return False
                
        except Exception as e:
            logger.warning("[confirm_order] popover confirm path failed: %s", e)
    
 
        # -----------------------------------------------------------------------
        
        # ======================================================================
        # B) MODAL confirmation path (The original logic, kept as fallback)
        # ======================================================================

        # logger.warning("[confirm_order] Found checkbox text but could not resolve popover container")
        # return False
        try:

            modal_selectors = (
                "#placeholder-for-modals .modal-dialog, "
                ".modal-dialog, "
                "[role='dialog'], "
                ".tv-modal, "
                ".dialog"
            )
            modals = page.locator(modal_selectors)
            mcount = await modals.count()

            # --- 1) Find a *confirmation* modal that has Buy/Sell + Cancel ----------
            # confirm_modal = None
            confirm_modal = await _find_confirm_modal_any(max_wait_ms=min(2500, t_ms))
            if confirm_modal is None:
                await dump_visible_clickables("NO CONFIRM UI FOUND (popover+modal missed)")
                logger.warning(
                    "[confirm_order] No confirmation modal with Buy/Sell + Cancel found; "
                    "will NOT click generic 'Send'."
                )
                return False

            
            # deadline = time.time() + min(t_ms / 1000.0, 2.0) # up to 2s just for modal appearance
            # poll = 0.05

            # try:
            #     while time.time() < deadline:
            #         try:
            #             cnt = await modals.count()
            #         except Exception:
            #             cnt = 0
            #         if cnt > 0:
            #             # confirm_modal = modals.nth(cnt - 1)
            #             logger.info("[confirm_order] modal appeared (count=%d)", cnt)
            #             break
            #         await asyncio.sleep(poll)

            
            # logger.info("[confirm_order] candidate modal count=%d", mcount)

            # for i in reversed(range(mcount)):  # top-most first
            #     m = modals.nth(i)
            #     try:
            #         if not await m.is_visible():
            #             continue
            #     except Exception:
            #         continue

            #     # if await m.locator("button", has_text=re.compile(r"Cancel", re.I)).count() == 0:
            #     if await m.locator(CLICKABLE, has_text=re.compile(r"Cancel", re.I)).count() == 0:
            #         continue
            #     # if await m.locator("button", has_text=re.compile(rf"^{target}$", re.I)).count() == 0:
            #     if await m.locator(CLICKABLE, has_text=re.compile(rf"^{target}$", re.I)).count() == 0:
            #         continue

            #     confirm_modal = m
            #     break

            # if confirm_modal is None:
            #     # NEW: log visible buttons on the whole page to see where Buy/Cancel lives
            #     await dump_visible_clickables("NO CONFIRM UI FOUND (popover+modal missed)")
            #     logger.warning(
            #         "[confirm_order] No confirmation modal with Buy/Sell + Cancel found; "
            #         "will NOT click generic 'Send'."
            #     )
            #     return False
            
            # btn = confirm_modal.locator("button", has_text=re.compile(rf"^{target}$", re.I)).first
            btn = confirm_modal.locator(self.clickable, has_text=re.compile(rf"^{target}$", re.I)).first
            if not await safe_click(btn, target):
                return False

            if await wait_gone(confirm_modal):
                return True

            logger.warning(
                "[confirm_order] modal still visible after clicking '%s'; treating as failure",
                target
            )
            return False

        except Exception as e:
            logger.warning("[confirm_order] modal confirm path failed: %s", e)
            return False

    
    # -------------------------- Frame-aware helpers ----------------------
    async def _find_confirm_popover(self, target: str, max_wait_ms: int):
        """
        Return the best matc hing confirmation popover locator, or None.
        Popover must contain:
            - 'MKT?' title
            - 'Do not show again'
            - Cancel
            - Confirm button matching target (Buy/Sell)
        """
        page = self._page
        deadline = time.time() + (max_wait_ms / 1000.0)

        # Poll for appearance (busy UI moments)
        best = None
        while time.time() < deadline:
            popovers = page.locator("div.popover")
            pcount = await popovers.count()

            for i in reversed(range(pcount)): # top-most/newest first
                p = popovers.nth(i)
                try:
                    if not await p.is_visible():
                        continue
                except Exception:
                    continue

                # Must look like the confirm popover
                try:
                    if await p.locator("text=/MKT\\?/i").count() == 0:
                        continue
                    if await p.locator("small", has_text=re.compile("Do not show again", re.I)).count() == 0:
                        continue
                    if await p.locator("div.btn.btn-default", has_text=re.compile(r"^Cancel$", re.I)).count() == 0:
                        continue
                    # if await p.locator("div.btn.btn-success", has_text=re.compile(rf"^{target}$", re.I)).count() == 0:
                    if await p.locator(self.clickable, has_text=re.compile(rf"^{target}$", re.I)).count() == 0:
                        continue
                except Exception:
                    continue

                best = p
                break
            
            if best is not None:
                return best

            await page.wait_for_timeout(50)

        return None


    async def _locator_any_frame(self, selectors, *, within=None):
        """
        Return the first locator that exist in Any frame.
        If within is provided, search within that locator only (no frames)
        """
        page = self._page
        if within is not None:
            for sel in selectors:
                loc = within.locator(sel)
                try:
                    if await loc.count() > 0:
                        return loc
                except Exception:
                    continue
            return None

        # search top-level + all frames
        frames = [page] + list(page.frames)
        for frame in frames:
            for sel in selectors:
                try:
                    loc = frame.locator(sel)
                    if await loc.count() > 0:
                        return loc
                except Exception:
                    continue
        return None

    def get_active_contract_symbol(self) -> str | None:
        """
        Best-effort: read the *actual* active contract shown by Tradovate
        (e.g. ESH6) from the DOM header area.
        Returns: string like "ESH6" or None if not found
        """

        # These are intentionally broad; we can refine them once we confirm the exact DOM.
        candidates = [
            # common contract header area
            ".contract-horizontal-info .info-column.info-column-symbol",
            ".contract-horizontal-info .contract-symbol",
            "#content .info-column.info-column-symbol",


            # chart/module header symbol text (sometimes appears here)
            ".module.chart .header",
            ".chart-wrapper .header",
        ]

        # Direct text reads
        for sel in candidates:
            try:
                txt = self._inner_text_any(sel, timeout_ms=800)
                if not txt:
                    continue

                t = " ".join(txt.split()).strip()

                # try to expect a futures-like symbol, e.g. ESH6, ESU6, ESM6, ESZ6, ESH7
                m = re.search(r"\b[A-Z]{1,4}[FGHJKLMNQUVXZ]\d{1,2}\b", t)
                if m:
                    return m.group(0)

                # fallback: sometimes only "ES" is present
                m2 = re.search(r"\bES\b", t)
                if m2:
                    return "ES"
            except Exception:
                continue

        return None


    async def _click_first_visible(self, locator, *, timeout_ms=4000):
        """
        Click the first visible+enabled element in a locator list.
        """
        try:
            n = await locator.count()
            for i in range(n):
                item = locator.nth(i)
                if await item.is_visible():
                    # avoid disabled buttons
                    disabled = await item.get_attribute("disabled")
                    aria_disabled = await item.get_attribute("aria-disabled")
                    if disabled or aria_disabled == "true":
                        continue
                    await item.scroll_into_view_if_needed()
                    await item.click(timeout=timeout_ms, force=True)
                    return True
        except Exception:
            return False
        return False


    def _all_contexts(self):
        """Return main page + all frames as contexts to search in."""
        ctxs = [self._page]
        # append all frames
        for fr in self._page.frames:
            # Skip the main frame (already added as page)
            if fr != self._page.main_frame:
                ctxs.append(fr)
        return ctxs


    def _locator_any(self, selector: str):
        """Return the first locator (page or name) that resolves for this selector."""
        for ctx in self._all_contexts():
            loc = ctx.locator(selector)
            try:
                cnt = self._run(loc.count())
                # Try a quick existence check without long waits
                # if loc.first.count() >= 0:
                if cnt and cnt > 0:
                    return loc
            except Exception:
                continue
        # Fallback to page locator so callers always get a Locator
        return self._page.locator(selector)


    def _wait_visible_any(self, keys_or_selectors, timeout_ms: int):
        """Wait until the selector is visible in any frame."""
        # sels = selectors if isinstance(selectors, (list, tuple)) else [selectors]
        sels = self._expand(keys_or_selectors) # alow keys or raw selectors
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        per_attempt_ms = 400

        while time.monotonic() < deadline:
            for sel in sels:
                remaining_ms = int((deadline - time.monotonic()) * 1000)
                if remaining_ms <= 0:
                    break
                try:
                    self._run(self._page.wait_for_selector(sel, timeout=min(per_attempt_ms,remaining_ms), state="visible"), timeout=min(per_attempt_ms, remaining_ms)/1000 + 5)
                    # return ctx.wait_for_selector(selector, timeout=300, state="visible")
                    return sel
                except Exception:
                    continue
        #     self._sleep_ms(100)
        # raise TimeoutError(f"Timed out waiting for visible: {sels}")
        return None


    def _fill_any(self, selector: str, text: str, timeout_ms: int = 10_000):
        """
        Fill the first matching input (across page + frames) with `text`.
        Wraps Playwright async calls via self._run so they actually execute
        """
        # accept selector key or raw selector
        sel_list = self._expand(selector) if not isinstance(selector, list) else selector
        # make sure at least one is visible somewhere
        self._wait_visible_any(sel_list, timeout_ms)

        for ctx in self._all_contexts():
            for sel in sel_list:
                try:
                    loc = ctx.locator(sel).first
                    # actually run the async fill coroutine
                    self._run(loc.fill(str(text), timeout=300), timeout=1.5)
                    # ctx.locator(selector).first.fill(text, timeout=300)
                    return
                except Exception:
                    continue
        raise RuntimeError(f"Failed to fill: {selector}")


    def _inner_text_any(self, selector: str, *, timeout_ms: int = 1200) -> str | None:
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        try:
            remaining = max(0.05, deadline - time.monotonic())
            # main page first
            self._run(self._page.wait_for_selector(selector, timeout=int(remaining * 1000), state="visible"), timeout=remaining + 0.5)
            return self._run(self._page.locator(selector).first.inner_text(), timeout=0.8)
        except Exception:
            pass

        # Trying every frame
        try:
            for fr in list(self._page.frames):
                remaining_ms = int(max(0.0, deadline - time.monotonic()) * 1000)
                if remaining_ms <= 0:
                    break
                try:
                    self._run(fr.wait_for_selector(selector, timeout=remaining_ms, state="visible"), timeout=(remaining_ms / 1000.0) + 1.0)
                    return self._run(fr.locator(selector).first.inner_text(), timeout=1.0)
        
                except Exception:
                    continue
        except Exception:
            pass
        return None
        # raise RuntimeError(f"Failed to read inner_text: {selector}")

    def _any_visible(self, selectors: list[str], timeout_ms: int) -> bool:
        for sel in selectors:
            try:
                self._wait_visible_any(sel, timeout_ms)
                return True
            except Exception:
                continue
        return False


    def _fill_quantity(self, quantity: float) -> bool:
        """Try several selectors to fill the Quantity field."""

        qty_text = str(quantity)
        selectors = [
            ".info-column-qty input.form-control",
            ".info-column-qty .select-input input",
            # Fallback: locate by the 'Quantity' label then its following input         
            "xpath=//small[contains(.,'Quantity')]/following::input[1]",
        ]
        # helper: type into active element (fallback)
        def _type_active():
            try:
                ae = None
                for ctx in self._all_contexts():
                    ae = ctx.evaluate_handle("() => document.activeElement")
                    if ae:
                        break
                self._run(self._page.keyboard.press("Meta+A"))
                self._run(self._page.keyboard.press("Control+A"))
                self._run(self._page.keyboard.press("Backspace"))
                self._run(self._page.keyboard.type(qty_text))
                return True
            except Exception:
                return False

        # 1) try normal fill with click-to-focus
        for sel in selectors:
            try:
                self._click_any(sel, timeout_ms=self.timeout_ms)
                # select-all & type in case .fill() is ignored
                try:
                    # use type path first (often more reliable for custom inputs)
                    self._run(self._page.keyboard.press("Meta+A"))
                    self._run(self._page.keyboard.press("Control+A"))
                    self._run(self._page.keyboard.press("Backspace"))
                    self._run(self._page.keyboard.type(qty_text))
                    # small settle wait
                    self._run(self._page.wait_for_timeout(200))
                except Exception:
                    pass

                # also try .fill() (some UIs need this)
                try:
                    self._fill_any(sel, qty_text, timeout_ms=1000)
                except Exception:
                    pass

                # 2) Verify it stuck (read back value via JS)
                for ctx in self._all_contexts():
                    try:
                        current = self._run(ctx.eval_on_selector(sel, "el => el && el.value"))
                        if str(current).strip() == qty_text:
                            return True
                    except Exception:
                        continue

                # 3) Force set via JS with proper events
                for ctx in self._all_contexts():
                    try:
                        ok = self._run(ctx.eval_on_selector(
                            sel,
                            """(el, v) => {
                                if (!el) return false;
                                el.focus();
                                el.value = v;
                                el.dispatchEvent(new Event('input', {bubbles:true}));
                                el.dispatchEvent(new Event('change', {bubbles:true}));
                                return true;
                            }
                            """,
                            qty_text
                        ))
                        if ok:
                            # verify again
                            current = self._run(ctx.eval_on_selector(sel, "el => el && el.value"))
                            if str(current).strip() == qty_text:
                                return True
                    except Exception:
                        continue
            except Exception:
                continue

        # 4) Last resort: click qty area, type into active element
        try:
            self._click_any(".info-column-qty", timeout_ms=self.timeout_ms)
            # type into active element
            try:
                self._run(self._page.keyboard.press("Meta+A"))
                self._run(self._page.keyboard.press("Control+A"))
                self._run(self._page.keyboard.press("Backspace"))
                self._run(self._page.keyboard.type(qty_text))
                return True
            # if _type_active():
            #     return True
            except Exception:
                pass
        except Exception:
            pass

        return False

    def _click_any(self, keys, timeout=None, timeout_ms=None):
        """Click the first visible selector from a list."""
        t_ms = self._norm_timeout_ms(timeout=timeout, timeout_ms=timeout_ms, default_ms=self.timeout_ms)
        selectors = self._expand(keys) if not isinstance(keys, list) else keys

        # t = int(timeout or getattr(self, "timeout_ms", 10000))
        last = None
        # for sel in self._expand(keys):
        for sel in selectors:
            try:
                self._run(self._page.wait_for_selector(sel, timeout=t_ms), timeout=t_ms/1000 + 5)
                self._run(self._page.click(sel))
                # loc = self._page.locator(sel).first
                # loc.wait_for(state="visible", timeout=timeout or self.timeout_ms)
                # loc.click()
                return True
            except Exception as e:
                last = e
        if last: raise last


    def _fill_first(self, keys, text, timeout=None, timeout_ms=None, clear=True):
        """Fill the first visible input from a list."""
        t_ms = self._norm_timeout_ms(timeout=timeout, timeout_ms=timeout_ms, default_ms=self.timeout_ms)
        selectors = self._expand(keys) if not isinstance(keys, list) else keys

        # t = int(timeout or getattr(self, "timeout_ms", 10000))
        last = None
        # for sel in self._expand(keys):
        for sel in selectors:
            try:
                self._run(self._page.wait_for_selector(sel, timeout=t_ms), timeout=t_ms/1000 + 5)
                # loc = self._page.locator(sel).first
                # loc.wait_for(state="visible", timeout=timeout or self.timeout_ms)
                if clear: 
                    try: 
                        self._run(self._page.fill(sel, ""))
                    except Exception: 
                        pass
                self._run(self._page.fill(sel, str(text)))
                return True
            except Exception as e:
                last = e
        if last: raise last

    def _norm_timeout_ms(self, timeout=None, timeout_ms=None, default_ms=None):
        if timeout_ms is not None:
            return int(timeout_ms)
        if timeout is not None:
            # callers sometimes pass seconds here; accept it/float
            try:
                return int(float(timeout) * 1000)
            except Exception:
                pass
        return int(default_ms if default_ms is not None else getattr(self, "timeout_ms", 3000))

    # -------------------------- tiny helpers -----------------------------

    def _safe_float(self, v):
        if v is None:
            return float("nan")
        try:
            return float(str(v))
        except:
            return float("nan")


    def _wait(self, selector: str, timeout: int = 10000):
        return self._run(self._page.wait_for_selector(selector, timeout=timeout), timeout=timeout/1000+5)

    def _click(self, selector: str, timeout: int = 10000):
        self._run(self._page.wait_for_selector(selector, timeout=timeout), timeout=timeout/1000+5)
        return self._run(self._page.click(selector))

    def _maybe_click(self, selector: str, timeout: int = 1500):
        "Best-effort click: accepts a selector KEY from JSON or a raw selector"
        try:
            return self._click_any(selector, timeout_ms=timeout)
        except Exception:
            return False

    def _fill(self, selector: str, value: str, timeout: int = 10000):
        self._run(self._page.wait_for_selector(selector, timeout=timeout), timeout=timeout/1000+5)
        return self._run(self._page.fill(selector, str(value)))

    def _inner_text(self, selector: str, timeout=10000):
        async def _do():
            el = await self._page.wait_for_selector(selector, timeout=timeout)
            return await el.inner_text()
        return self._run(_do(), timeout=timeout/1000 + 5)

    def _attr(self, selector: str, name: str, timeout: int | None = None) -> str | None:
        """Return attribute value or None."""
        t = int(timeout or getattr(self, "timeout_ms", 10000))
        async def _do():
            el = await self._page.wait_for_selector(selector, timeout=t)
            return await el.get_attribute(name)
        return self._run(_do(), timeout=t/1000 + 5)
        # self._wait(selector, self.timeout_ms)
        # return self._page.locator(selector).get_attribute(name)

    def _all(self, selector: str, timeout: int | None = None):
        """Return a list of ElementHandle for selector (be mindful: they are async handles)"""
        t = int(timeout or getattr(self, "timeout_ms", 10000))
        async def _do():
            await self._page.wait_for_selector(selector, timeout=t)
            return await self._page.query_selector_all(selector)
        return self._run(_do(), timeout=t/1000 + 5)
        # self._wait(selector, self.timeout_ms)
        # return self._page_locator(selector).all()

    def _scrape_ladder(self, row_selector: str, depth: int):
        """
        Read DOM ladder rows. Returns [[price, qty], ...].
        Expects rows having attributes: data-price, data-qty.
        """
        async def _do():
            rows = await self._page.query_selector_all(row_selector)
            out = []
            for r in rows[:depth]:
                px = await r.get_attribute("data-price")
                qty = await r.get_attribute("data-qty")
                fp = self._to_float(px)
                fq = self._to_float(qty)
                if fp == fp: # not NaN
                    out.append([fp, fq])
            return out
        return self._run(_do())

    def _to_float(self, v: str | None) -> float:
        try:
            if v is None:
                return float("nan")
            return float(str(v).replace(",", "").strip())
        except Exception:
            return float("nan")


    def _snapshot(self, label: str):
        """Save a screenshot and HTML snapshot to help debug selectors."""
        async def _do():
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            try:
                # ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                await self._page.screenshot(path=f"ui_error_{label}_{ts}.png", full_page=True)
            except Exception:
                pass
            try:
                html = await self._page.content()
                with open(f"ui_error_{label}_{ts}.html", "w", encoding="utf-8") as f:
                    f.write(html)
            except Exception:
                pass
        try:
            self._run(_do(), timeout=20)
        except Exception:
            pass

    
    def _expand(self, keys_or_selectors):
        """Expand a key (mapped in self._sel) or return selectors as-is."""
        items = keys_or_selectors if isinstance(keys_or_selectors, list) else [keys_or_selectors]
        out = []
        for item in items:
            if isinstance(item, str) and hasattr(self, "_sel") and item in self._sel:
                val = self._sel[item]
                out += (val if isinstance(val, list) else [val])
            else:
                out.append(item)
        return out


    def _is_visible(self, selector: str, timeout: int = 1500) -> bool:
        try:
            el = self._run(self._page.wait_for_selector(selector, timeout=timeout), timeout=timeout/1000+5)
            return el is not None
        except Exception:
            return False


    def probe_logged_in(self) -> dict:
        """
        Return booleans indicating if key controls are visible
        """
        try:
            return {
                "buy_button": self._is_visible("order.buy_market"),
                "sell_button": self._is_visible("order.sell_market"),
                "qty_input": self._is_visible("order.qty_input"),
                "positions_tab": self._is_visible("positions.tab"),
                "orders_tab": self._is_visible("orders.tab"),
                "balance_pane": self._is_visible("account.balance_pane"),
                "logged_marker_any": any(self._is_visible(x) for x in self._sel.get("app.logged_in_marker.any", []))

            }
        except Exception as e:
            return {"error": str(e)}


    def probe_selectors(self) -> dict:
        """
        Try to locate core elements we need. Returns a dict of booleans.
        Won't submit orders.
        """
        self._ensure_page()
        results = {}

        def ok(name, fn):
            try:
                fn()
                results[name] = True
            except Exception:
                results[name] = False

        ok("buy_button", lambda: self._wait_visible_any(".market-buttons >> text=Buy Mkt", self.timeout_ms))
        ok("sell_button", lambda: self._wait_visible_any(".market-buttons >> text=Sell Mkt", self.timeout_ms))
        ok("qty_input", lambda: (_ for _ in ()).throw(
            Exception("no qty")
        ) if not self._any_visible([
            ".info-column-qty input.form-control",
            ".info-column-qty .select-input input",
            "xpath=//small[contains(., 'Quantity')]/following::input[1]"
        ], self.timeout_ms) else None) 
        ok("orders_tab", lambda: self._wait_visible_any("ul.lm_tabs .lm_title:has-text('Orders')", self.timeout_ms))
        # Positions might be in dropdown depending on your layout; try both:
        ok("positions_tab", lambda: self._wait_visible_any("ul.lm_tabs .lm_title:has-text('Positions')", self.timeout_ms))
        ok("positions_dropdown", lambda: self._wait_visible_any(".lm_tabdropdown_list .lm_title:has-text('Positions')", self.timeout_ms))
        ok("account_inline_balance", lambda: self._wait_visible_any(".account-info-inline .balance-view .balance-row", self.timeout_ms))
        return results


    def get_historical_data(self, symbol: str, timeframe: str, limit: int = 100):
        """
        Minimal placeholder so the adapter can be instantiated.
        UI automation can't fetch OHLC from the page reliably without 
        a chart data API or passing the canvas. Return an empty list for now.
        Your DataManager already tolerates empty and logs a warning.
        """
        # Option A (empty): unlock instantiation & let higher layers handle no data
        return []

        # Option B (optional later): if you open a quotes/history panel in the DOM,
        # parse rows and return a list of dicts with keys:
        # timestamp (ms), open, high, low, close, volume

    def get_order_history(self, symbol: str = None, limit: int = 100):
        """
        Minimal placeholder, when we place/cancel in SIM later,
        we can scrape the Orders/History panel to populate this.
        """
        # Return an empty list for now so the interface is satisfied.
        return []


    def _wait_any(self, keys_or_selectors: list[str], timeout=None, timeout_ms: int = None) -> str | None:
        """
        Wait until any selector is visible; return the one that matched.
        Returns the selector string that matched, or None if timed out.
        """
        t_ms = self._norm_timeout_ms(timeout=timeout, timeout_ms=timeout_ms, default_ms=self.timeout_ms)

        # expand strings keys via the selector map; keeping list support
        selectors = self._expand(keys_or_selectors) if not isinstance(keys_or_selectors, list) else keys_or_selectors

        deadline = time.monotonic() + (t_ms / 1000.0)
        # last_err = None
        # small per-attempt timeout so we can iterate over all selectors repeatedly
        per_attempt_ms = 400

        while time.monotonic() < deadline:
            for sel in selectors:
                remaining_ms = int((deadline - time.monotonic()) * 1000)
                if remaining_ms <= 0:
                    break
                try:
                    self._run(self._page.wait_for_selector(sel, timeout=min(per_attempt_ms, remaining_ms), state='visible'), timeout=min(per_attempt_ms, remaining_ms)/1000+5)
                    return sel
                except Exception as e:
                    # last_error = e
                    # Try the next selector
                    continue
        return None


    def _connect_fail(self, label: str, e: Exception):
        print(f"connect() failed at {label}: {e}")
        try:
            self._snapshot(f"connect_fail_{label}")
        except Exception:
            pass



    def _modal_is_open(self) -> bool:
        try:
            cnt = self._run(self._page.locator("#placeholder-for-modals .modal.in").count(), timeout=0.8)
            return bool(cnt and cnt > 0)
        except Exception:
            return False


    def _close_any_modal(self):
        """Best-effort: close order confirm or any sticky modal."""
        try:
            # prefer explicit Cancel buttons, then the 'X'
            self._click_any([
                "#placeholder-for-modals .modal.in .btn:has-text('Cancel')",
                "#placeholder-for-modals .modal.in button:has-text('Cancel')",
                "#placeholder-for-modals .modal.in .close"
            ], timeout=800)
        except Exception:
            # last-resort: remove backdrop via JS so clicks aren't intercepted
            try:
                self._run(self._page.evaluate(
                    "() => { const bd = document.querySelector('.modal-backdrop.in'); if (bd) bd.remove(); }"
                ), timeout=0.8)
            except Exception:
                pass


    def _pre_click_hygiene(self):
        """Clear anything that could intercept clicks before pressing Buy/Sell."""
        # If a previous consfirm is open, close/cancel it first
        if self._modal_is_open():
            self._close_any_modal()
        # Also clear any leftover backdrops
        try:
            self._run(self._page.evaluate(
                "() => { const bd = document.querySelector('.modal-backdrop.in'); if (bd) bd.remove(); }"
            ), timeout=0.8)
        except Exception:
            pass