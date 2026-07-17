# -*- coding: utf-8 -*-
"""
阶梯价格设置模块
重构自: main_属性融合.py 中的 set_ladder_price()
"""
import os
import math
import time
import random
from typing import Dict, List, Optional, Tuple

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from app.core.settings import DeliveryConfig, PriceConfig
from app.core.logger import setup_logger

logger = setup_logger("price_setter")

_REACT_SET_INPUT = """
function setInput(inp, val) {
  if (!inp || inp.disabled) return false;
  inp.focus();
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(inp, val);
  inp.dispatchEvent(new Event('input', {bubbles: true}));
  inp.dispatchEvent(new Event('change', {bubbles: true}));
  inp.blur();
  return (inp.value || '').trim() === String(val).trim();
}
"""


def _read_sell_select_js(row_id: str) -> str:
    return f"""
    const root = document.getElementById('{row_id}');
    if (!root) return '';
    const em = root.querySelector('.next-select-values em');
    const t = (em?.getAttribute('title') || em?.innerText || '').trim();
    if (t && t !== '请选择') return t;
    const spans = root.querySelectorAll('.next-select-values [aria-hidden=true] span');
    for (const s of spans) {{
      const x = (s.innerText || '').trim();
      if (x && x !== '请选择' && x !== '\\u00a0') return x;
    }}
    return '';
    """


def _sale_unit_filled(driver) -> bool:
    try:
        unit = str(driver.execute_script(_read_sell_select_js("priceUnit")) or "").strip()
        return bool(unit and unit != "请选择")
    except Exception:
        return False


def _sale_type_filled(driver, expected: str) -> bool:
    try:
        current = str(driver.execute_script(_read_sell_select_js("saleType")) or "").strip()
        if not current:
            return False
        return not expected or current == expected or expected in current or current in expected
    except Exception:
        return False


def _delivery_filled(driver) -> bool:
    try:
        return bool(
            driver.execute_script(
                """
                const root = document.getElementById('struct-ladderPeriod');
                if (!root) return false;
                let complete = 0;
                for (const row of root.querySelectorAll('tbody tr.next-table-row')) {
                  const q = (row.querySelector('input[role=input-quantity]')?.value || '').trim();
                  const d = (row.querySelector('input[role=input-day]')?.value || '').trim();
                  if (q && d && +q > 0 && +d > 0) complete++;
                }
                return complete > 0;
                """
            )
        )
    except Exception:
        return False


def _select_sell_o_option(driver, row_id: str, value: str, *, searchable: bool = False) -> bool:
    value = str(value or "").strip()
    if not value:
        return False
    try:
        row = driver.find_element(By.ID, row_id)
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", row)
        trigger = row.find_element(By.CSS_SELECTOR, ".next-select-trigger, .sell-o-select")
        driver.execute_script("arguments[0].click();", trigger)
        time.sleep(0.25)
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".next-overlay-wrapper.opened .sell-o-select-options")
            )
        )
        if searchable:
            for inp in driver.find_elements(
                By.CSS_SELECTOR, ".next-overlay-wrapper.opened .options-search input"
            ):
                if not inp.is_displayed():
                    continue
                search_key = value.split("/")[0].strip() or value
                inp.click()
                inp.send_keys(Keys.CONTROL + "a")
                inp.send_keys(search_key)
                time.sleep(0.35)
                break
        clicked = bool(
            driver.execute_script(
                """
                const val = arguments[0];
                for (const item of document.querySelectorAll('.next-overlay-wrapper.opened .options-item')) {
                  if (!item.offsetParent) continue;
                  const t = (item.innerText || '').trim();
                  if (!t) continue;
                  if (t === val || t.includes(val) || val.includes(t)) {
                    item.click();
                    return true;
                  }
                }
                return false;
                """,
                value,
            )
        )
        time.sleep(0.2)
        return clicked
    except Exception as exc:
        logger.warning(f"下拉选择失败 {row_id}={value}: {exc}")
        return False


def fill_sale_unit(driver, price_config: PriceConfig) -> bool:
    """填写售卖单位（阶梯价之前）。计量单位已有值则跳过。"""
    sale_type = str(getattr(price_config, "sale_type", "") or "按件卖").strip()
    price_unit = str(getattr(price_config, "price_unit", "") or "").strip()

    if not price_unit:
        logger.info("未配置计量单位，跳过售卖单位")
        return True

    try:
        area = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "struct-priceUnit"))
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", area)
        time.sleep(0.2)
    except Exception as exc:
        logger.warning(f"未找到售卖单位区域: {exc}")
        return False

    if _sale_unit_filled(driver):
        logger.info("计量单位已有值，跳过售卖单位填写")
        return True

    if sale_type and not _sale_type_filled(driver, sale_type):
        if _select_sell_o_option(driver, "saleType", sale_type):
            logger.info(f"基础销售方式已选: {sale_type}")
        else:
            logger.warning(f"基础销售方式选择失败: {sale_type}")

    if not _select_sell_o_option(driver, "priceUnit", price_unit, searchable=True):
        logger.warning(f"计量单位选择失败: {price_unit}")
        return False
    logger.info(f"计量单位已选: {price_unit}")

    return _sale_unit_filled(driver)


def fill_delivery_period(driver, delivery_config: DeliveryConfig) -> bool:
    """填写发货期阶梯（可售数量之后）。已有完整区间则跳过。"""
    tiers: List[Dict[str, int]] = list(getattr(delivery_config, "ladder_delivery", None) or [])
    tiers = [t for t in tiers if int(t.get("delivery_days") or 0) > 0]
    if not tiers:
        logger.info("未配置发货期阶梯，跳过")
        return True

    if _delivery_filled(driver):
        logger.info("发货期已有值，跳过")
        return True

    try:
        area = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "struct-ladderPeriod"))
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", area)
        time.sleep(0.3)
    except Exception as exc:
        logger.warning(f"未找到发货期区域: {exc}")
        return False

    target_rows = min(len(tiers), 3)
    try:
        while True:
            delete_btns = driver.find_elements(
                By.XPATH,
                "//div[@id='struct-ladderPeriod']//button[@role='remove' and contains(.,'删除')]",
            )
            clickable = [b for b in delete_btns if b.is_enabled() and b.is_displayed()]
            row_count = len(
                driver.find_elements(
                    By.XPATH,
                    "//div[@id='struct-ladderPeriod']//tbody//tr[contains(@class,'next-table-row')]",
                )
            )
            if row_count <= 1 or not clickable:
                break
            driver.execute_script("arguments[0].click();", clickable[0])
            time.sleep(0.3)

        current_rows = len(
            driver.find_elements(
                By.XPATH,
                "//div[@id='struct-ladderPeriod']//tbody//tr[contains(@class,'next-table-row')]",
            )
        )
        need_add = target_rows - current_rows
        if need_add > 0:
            add_btn = WebDriverWait(driver, 8).until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//div[@id='struct-ladderPeriod']//button[@role='btn-add']")
                )
            )
            for _ in range(need_add):
                driver.execute_script("arguments[0].click();", add_btn)
                time.sleep(0.4)

        rows = driver.find_elements(
            By.XPATH,
            "//div[@id='struct-ladderPeriod']//tbody//tr[contains(@class,'next-table-row')]",
        )
        if len(rows) < target_rows:
            logger.warning(f"发货期行数不足: {len(rows)}/{target_rows}")
            return False

        for idx in range(target_rows):
            tier = tiers[idx]
            max_order = int(tier.get("max_order") or 0)
            days = int(tier.get("delivery_days") or 0)
            row = rows[idx]
            if max_order > 0:
                q_inp = row.find_element(By.XPATH, ".//input[@role='input-quantity']")
                q_inp.click()
                q_inp.send_keys(Keys.CONTROL + "a")
                q_inp.send_keys(str(max_order))
                driver.execute_script("arguments[0].blur();", q_inp)
            d_inp = row.find_element(By.XPATH, ".//input[@role='input-day']")
            d_inp.click()
            d_inp.send_keys(Keys.CONTROL + "a")
            d_inp.send_keys(str(days))
            driver.execute_script("arguments[0].blur();", d_inp)
            time.sleep(0.15)

        logger.info(f"发货期已设置: {tiers[:target_rows]}")
        return True
    except Exception as exc:
        logger.warning(f"发货期填写异常: {exc}")
        return False


def set_ladder_price(
    driver,
    main_dir: str,
    price_config: PriceConfig,
    delivery_config: Optional[DeliveryConfig] = None,
) -> bool:
    """
    设置阶梯价格 + 可售数量（对齐老脚本）

    - 从 main_dir/出厂价格.csv 读取出厂价
    - 按区间同向浮动计算4档阶梯价
    - 填写阶梯价表格
    - 填写 SKU 可售数量
    """
    # 1) 读取出厂价
    ex_price = _read_factory_price(main_dir)
    if ex_price is None:
        logger.error("出厂价格读取失败")
        return False

    # 2) 计算阶梯价（同向浮动 + 向上取整）
    ladder_config = _calculate_ladder_prices(ex_price, price_config)
    if not ladder_config:
    logger.error(
        "价格模板为空或不完整，请先填写汇率和至少一档阶梯价格"
    )
    return False

    logger.info(f"出厂价: {ex_price}元, 阶梯价格: {ladder_config}")

    try:
        # 3) 滚动到阶梯价区域
        ladder_price_area = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "struct-ladderPrice"))
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", ladder_price_area)
        time.sleep(1)

        # 4) 删除多余行（保留1行）
        while True:
            delete_btns = driver.find_elements(
                By.XPATH,
                "//div[@id='struct-ladderPrice']//button[@role='remove' and contains(.,'删除')]"
            )
            clickable_btns = [btn for btn in delete_btns if btn.is_enabled() and btn.is_displayed()]
            if not clickable_btns:
                break
            driver.execute_script("arguments[0].click();", clickable_btns[0])
            time.sleep(0.8)

        # 5) 清空默认行
        default_row = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((
                By.XPATH,
                "//div[@id='struct-ladderPrice']//table//tbody//tr[contains(@class, 'next-table-row')]"
            ))
        )
        for field in ["quantity", "price"]:
            input_el = default_row.find_element(By.XPATH, f".//input[@role='input-{field}']")
            input_el.click()
            input_el.send_keys(Keys.CONTROL + "a")
            input_el.send_keys(Keys.BACKSPACE)
            driver.execute_script("arguments[0].blur();", input_el)

        # 6) 新增至4行
        target_rows = len(ladder_config)
        current_rows = len(driver.find_elements(
            By.XPATH,
            "//div[@id='struct-ladderPrice']//table//tbody//tr[contains(@class, 'next-table-row')]"
        ))
        need_add = target_rows - current_rows
        if need_add > 0:
            add_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((
                    By.XPATH,
                    "//div[@id='struct-ladderPrice']//button[@role='btn-add' and contains(.,'新增价格区间')]"
                ))
            )
            for _ in range(need_add):
                driver.execute_script("arguments[0].click();", add_btn)
                time.sleep(1)

        # 7) 填入4行价格
        ladder_rows = WebDriverWait(driver, 5).until(
            EC.presence_of_all_elements_located((
                By.XPATH,
                "//div[@id='struct-ladderPrice']//table//tbody//tr[contains(@class, 'next-table-row')]"
            ))
        )
        if len(ladder_rows) != target_rows:
            logger.error(f"阶梯价行数异常：当前{len(ladder_rows)}行，需要{target_rows}行")
            return False

        for idx in range(target_rows):
            row = ladder_rows[idx]
            min_order, price = ladder_config[idx]
            q_input = row.find_element(By.XPATH, ".//input[@role='input-quantity']")
            q_input.click()
            q_input.send_keys(Keys.CONTROL + "a")
            q_input.send_keys(str(min_order))
            driver.execute_script("arguments[0].blur();", q_input)

            p_input = row.find_element(By.XPATH, ".//input[@role='input-price']")
            p_input.click()
            p_input.send_keys(Keys.CONTROL + "a")
            p_input.send_keys(str(price))
            driver.execute_script("arguments[0].blur();", p_input)
            time.sleep(0.3)

        logger.info("阶梯价格设置完成")

        # 8) 填入可售数量
        inventory = getattr(price_config, "product_inventory", None)
        if inventory is not None:
            _fill_sku_inventory(driver, int(inventory))
        else:
            logger.info("未配置可售数量，跳过 SKU 库存填写")


        # 8b) 发货期（可售数量之后）
        if delivery_config is not None:
            try:
                fill_delivery_period(driver, delivery_config)
            except Exception as exc:
                logger.warning(f"发货期填写异常（非致命）: {exc}")

        # 9) 样品服务（须在商品编码之前，编码填完立即进入属性填写）
        ladder_max = max(p for _, p in ladder_config) if ladder_config else int(math.ceil(ex_price / price_config.exchange_rate))
        set_sample_service(driver, price_config, ladder_max_usd=ladder_max)

        # 10) 商品编码（本模块最后一步，填完即进入属性）
        sku_code = str(getattr(price_config, "sku_outer_id", "") or "").strip()
        if sku_code:
            _fill_sku_outer_id(driver, sku_code)
        else:
            logger.warning("未配置商品编码，跳过 SKU 商品编码填写")
        return True

    except Exception as e:
        logger.error(f"阶梯价格设置异常: {e}")
        return False


def _read_factory_price(main_dir: str) -> Optional[float]:
    """读取出厂价格.csv"""
    price_file = os.path.join(main_dir, "出厂价格.csv")
    if not os.path.exists(price_file):
        return None
    try:
        with open(price_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return None
            price = float(content)
            if price <= 0:
                return None
            return price
    except Exception:
        return None


def _calculate_ladder_prices(
    ex_price: float,
    config: PriceConfig,
) -> List[Tuple[int, int]]:
    """计算阶梯价格；空值或不完整档位不参与计算。"""
    exchange_rate = float(
        getattr(config, "exchange_rate", None) or 0
    )
    if exchange_rate <= 0:
        return []

    offset_ratio = (
        random.random() if config.enable_random_float else 0.0
    )
    orders = list(
        getattr(config, "ladder_min_orders", None) or []
    )
    ranges = list(
        getattr(config, "ladder_factor_ranges", None) or []
    )

    ladder_config: List[Tuple[int, int]] = []
    for i in range(min(len(orders), len(ranges))):
        row = ranges[i] or []
        if (
            orders[i] is None
            or len(row) < 2
            or row[0] is None
            or row[1] is None
        ):
            continue

        min_order = int(orders[i])
        low = float(row[0])
        high = float(row[1])
        factor = low + offset_ratio * (high - low)
        price = math.ceil(ex_price * factor / exchange_rate)
        ladder_config.append((min_order, price))

    return ladder_config



def _fill_sku_inventory(driver, inventory: int):
    """填写每个规格的可售数量（对齐老脚本）"""
    try:
        sku_area = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "struct-sku"))
        )
        driver.execute_script(
            """
            const skuArea = document.getElementById('struct-sku');
            const virtualTable = skuArea.querySelector('.virtualized-table-scroll-wrapper');
            if (virtualTable) {
                virtualTable.scrollTop = 0;
                virtualTable.scrollIntoView({block: 'center'});
            }
            """
        )
        time.sleep(0.5)

        virtual_table_tbody = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, "//div[@class='virtualized-table-body']//table//tbody"))
        )
        sku_stock_cells = virtual_table_tbody.find_elements(
            By.XPATH,
            ".//td[contains(@class, 'cell-skuStock') and @data-name='skuStock']"
        )

        filled_count = 0
        for cell in sku_stock_cells:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", cell)
                time.sleep(0.08)
                stock_input = cell.find_element(
                    By.XPATH,
                    ".//input[@placeholder='请输入' and @minimum='0' and @maximum='999999999']"
                )
                stock_input.click()
                stock_input.send_keys(Keys.CONTROL + "a")
                stock_input.send_keys(str(inventory))
                driver.execute_script(
                    """
                    const input = arguments[0];
                    input.dispatchEvent(new Event('input', {bubbles: true}));
                    input.dispatchEvent(new Event('change', {bubbles: true}));
                    input.blur();
                    """,
                    stock_input,
                )
                filled_count += 1
            except Exception:
                continue

        logger.info(f"成功为{filled_count}个规格填入可售数量={inventory}")
    except Exception as e:
        logger.warning(f"可售数量填入异常（非致命）: {e}")


def _fill_sku_outer_id(driver, sku_code: str):
    """填写每个 SKU 行的商品编码（struct-sku / cell-skuOuterId）。"""
    sku_code = str(sku_code or "").strip()
    if not sku_code:
        return
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "struct-sku"))
        )
        driver.execute_script(
            """
            const skuArea = document.getElementById('struct-sku');
            if (skuArea) {
              const virtualTable = skuArea.querySelector('.virtualized-table-scroll-wrapper');
              if (virtualTable) {
                virtualTable.scrollTop = 0;
                virtualTable.scrollIntoView({block: 'center'});
              }
            }
            """
        )
        time.sleep(0.3)

        filled = int(
            driver.execute_script(
                _REACT_SET_INPUT
                + """
                const code = String(arguments[0] || '').trim();
                if (!code) return 0;
                const root = document.getElementById('struct-sku');
                if (!root) return 0;
                let n = 0;
                const batchInp = root.querySelector(
                  'input[placeholder*="商品编码批量"], input[placeholder*="批量设置"]'
                );
                if (batchInp && setInput(batchInp, code)) n++;
                const cells = root.querySelectorAll('td.cell-skuOuterId[data-name="skuOuterId"]');
                for (const cell of cells) {
                  const inp = cell.querySelector('input');
                  if (inp && setInput(inp, code)) n++;
                }
                return n;
                """,
                sku_code,
            )
            or 0
        )
        if filled:
            logger.info(f"成功填入商品编码={sku_code}（{filled} 处）")
        else:
            logger.warning(f"商品编码未填入: {sku_code}")
        driver.execute_script(
            """
            const targets = ['struct-icbuCatProp', 'struct-catProp', 'struct-productAttributes'];
            for (const id of targets) {
              const el = document.getElementById(id);
              if (el) { el.scrollIntoView({block: 'start', behavior: 'instant'}); return; }
            }
            const first = document.querySelector('[id^="struct-p-"]');
            if (first) first.scrollIntoView({block: 'start', behavior: 'instant'});
            """
        )
    except Exception as e:
        logger.warning(f"商品编码填入异常（非致命）: {e}")


def set_sample_service(
    driver,
    price_config: PriceConfig,
    *,
    ladder_max_usd: int = 0,
    sample_price_usd: Optional[int] = None,
    quantity: Optional[int] = None,
) -> bool:
    """
    设置样品服务：支持样品、轻定制、索样数量、样品 SKU 价格。
    参考 struct-marketSample / struct-customizationSupportSample / struct-sampleSku
    """
    if not getattr(price_config, "sample_service_enabled", True):
        logger.info("配置关闭样品服务，选择「不支持」")
        _select_sample_radio(driver, support=False)
        return True

    raw_cfg = getattr(price_config, "sample_sku_price_usd", None)
    configured_price = float(raw_cfg) if raw_cfg is not None else 0.0
    if sample_price_usd is not None and sample_price_usd > 0:
        usd = int(sample_price_usd)
    elif configured_price > 0:
        usd = int(configured_price)
    else:
        usd = max(1, int(ladder_max_usd or 1))

    qty = int(quantity if quantity is not None else getattr(price_config, "sample_max_quantity", 1) or 1)
    light_custom = bool(getattr(price_config, "sample_support_light_customization", False))
    price_str = str(max(1, usd))
    qty_str = str(max(1, qty))

    try:
        _select_sample_radio(driver, support=True)
        time.sleep(0.2)
        _select_light_customization(driver, support=light_custom)

        driver.execute_script(
            """
            const qty = arguments[0];
            const inp = document.getElementById('marketSamplingQuantity');
            if (!inp) return false;
            inp.scrollIntoView({block:'center'});
            inp.focus();
            inp.value = qty;
            inp.dispatchEvent(new Event('input', {bubbles:true}));
            inp.dispatchEvent(new Event('change', {bubbles:true}));
            inp.blur();
            return true;
            """,
            qty_str,
        )
        time.sleep(0.2)

        sample_root = driver.find_elements(By.ID, "struct-sampleSku")
        if not sample_root:
            logger.info("页面无样品 SKU 区块，跳过")
            return True

        driver.execute_script(
            "document.getElementById('struct-sampleSku')?.scrollIntoView({block:'center'});"
        )
        time.sleep(0.3)

        filled = _fill_sample_sku_prices(driver, price_str)
        if not filled:
            filled = _fill_sample_sku_rows_selenium(driver, price_str)

        logger.info(
            f"样品服务已设置: 支持=是, 轻定制={'是' if light_custom else '否'}, "
            f"索样={qty_str}, 样品价USD={price_str}, SKU行={filled or 'selenium'}"
        )
        return True
    except Exception as exc:
        logger.warning(f"样品服务设置异常（非致命）: {exc}")
        return False


def _select_sample_radio(driver, *, support: bool) -> None:
    want = "支持" if support else "不支持"
    driver.execute_script(
        """
        const want = arguments[0];
        const root = document.getElementById('struct-marketSample') || document.getElementById('marketSample');
        if (!root) return;
        root.scrollIntoView({block:'center'});
        for (const item of root.querySelectorAll('.radio-item')) {
          const t = (item.innerText || '').trim();
          if (t !== want) continue;
          const lab = item.querySelector('label') || item;
          lab.click();
          return;
        }
        """,
        want,
    )


def _select_light_customization(driver, *, support: bool) -> None:
    want = "支持" if support else "不支持"
    driver.execute_script(
        """
        const want = arguments[0];
        const root = document.getElementById('struct-customizationSupportSample')
          || document.getElementById('customizationSupportSample');
        if (!root) return;
        for (const item of root.querySelectorAll('.radio-item')) {
          const t = (item.innerText || '').trim();
          if (t !== want) continue;
          const wrap = item.querySelector('.next-radio-wrapper');
          if (wrap && wrap.classList.contains('disabled')) return;
          const lab = item.querySelector('label') || item;
          lab.click();
          return;
        }
        """,
        want,
    )


def _fill_sample_sku_prices(driver, price_str: str) -> int:
    """启用样品行并填写价格（含表头批量价 + 逐行）。"""
    return int(
        driver.execute_script(
            _REACT_SET_INPUT
            + """
            const price = arguments[0];
            const root = document.getElementById('struct-sampleSku');
            if (!root) return 0;
            let n = 0;
            const batchInp = root.querySelector(
              '.th-skuStock-input input, input[placeholder*="批量"], input[placeholder*="batch"]'
            );
            if (batchInp && setInput(batchInp, price)) n++;
            const tbody = root.querySelector('.virtualized-table-body tbody')
              || root.querySelector('.sku-wrapper-sampleSku tbody');
            if (!tbody) return n;
            for (const row of tbody.querySelectorAll('tr')) {
              const op = row.querySelector('td.cell-operate');
              const priceTd = row.querySelector('td.cell-price');
              if (!op || !priceTd) continue;
              if (op.classList.contains('disabled')) continue;
              const sw = op.querySelector('[role=switch]');
              if (sw && sw.getAttribute('aria-checked') === 'false') {
                sw.click();
              }
              let inp = null;
              for (let t = 0; t < 25; t++) {
                inp = priceTd.querySelector('input:not([disabled])');
                if (inp) break;
                const start = Date.now();
                while (Date.now() - start < 40) {}
              }
              if (!inp) continue;
              if (setInput(inp, price)) n++;
            }
            return n;
            """,
            price_str,
        )
        or 0
    )


def _fill_sample_sku_rows_selenium(driver, price_str: str) -> int:
    """Selenium 回退：逐行启用样品 SKU 并填价。"""
    count = 0
    try:
        root = driver.find_element(By.ID, "struct-sampleSku")
        rows = root.find_elements(By.CSS_SELECTOR, ".virtualized-table-body tbody tr")
        for row in rows:
            try:
                op = row.find_element(By.CSS_SELECTOR, "td.cell-operate")
                if "disabled" in (op.get_attribute("class") or ""):
                    continue
                sw = op.find_elements(By.CSS_SELECTOR, "[role=switch]")
                if sw and sw[0].get_attribute("aria-checked") == "false":
                    driver.execute_script("arguments[0].click();", sw[0])
                    time.sleep(0.12)
                price_td = row.find_element(By.CSS_SELECTOR, "td.cell-price")
                inp = None
                for _ in range(4):
                    try:
                        inp = price_td.find_element(By.CSS_SELECTOR, "input:not([disabled])")
                        if inp and inp.is_enabled():
                            break
                    except Exception:
                        pass
                    time.sleep(0.05)
                if not inp:
                    continue
                inp.click()
                inp.send_keys(Keys.CONTROL + "a")
                inp.send_keys(Keys.BACKSPACE)
                inp.send_keys(price_str)
                driver.execute_script(
                    """
                    arguments[0].dispatchEvent(new Event('input',{bubbles:true}));
                    arguments[0].dispatchEvent(new Event('change',{bubbles:true}));
                    arguments[0].blur();
                    """,
                    inp,
                )
                if (inp.get_attribute("value") or "").strip() == price_str:
                    count += 1
            except Exception:
                continue
    except Exception:
        pass
    return count
