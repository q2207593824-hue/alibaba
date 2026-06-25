# -*- coding: utf-8 -*-
"""Clear country/region checkboxes to avoid country ladder price requirement."""
import time

from app.core.logger import setup_logger

logger = setup_logger("country_region")

_CLEAR_AND_COUNT_JS = """
const root = document.getElementById('struct-icbuCountryRegion')
  || document.getElementById('icbuCountryRegion');
if (!root) return {ready: false, toggled: 0, remaining: -1};
function isOn(cb) {
  const wrap = cb.closest('.next-checkbox-wrapper');
  const inner = wrap && wrap.querySelector('.next-checkbox');
  if (inner && inner.classList.contains('checked')) return true;
  if (cb.getAttribute('aria-checked') === 'true') return true;
  return !!cb.checked;
}
let toggled = 0;
for (let round = 0; round < 20; round++) {
  const boxes = root.querySelectorAll(
    '.countryCheckboxGroup input[type=checkbox], input.next-checkbox-input[type=checkbox]'
  );
  let target = null;
  for (const cb of boxes) {
    if (isOn(cb)) { target = cb; break; }
  }
  if (!target) break;
  const wrap = target.closest('.next-checkbox-wrapper');
  if (wrap) wrap.click();
  else {
    target.checked = false;
    target.removeAttribute('checked');
    target.setAttribute('aria-checked', 'false');
    target.dispatchEvent(new Event('change', {bubbles: true}));
  }
  toggled++;
}
let remaining = 0;
for (const cb of root.querySelectorAll('input[type=checkbox]')) {
  if (isOn(cb)) remaining++;
}
const ladder = document.getElementById('struct-countryLadderPrice');
return {
  ready: true,
  toggled,
  remaining,
  ladder_visible: !!(ladder && ladder.offsetParent),
};
"""


def clear_country_region_selection(driver) -> bool:
    """Uncheck all countries in struct-icbuCountryRegion (one global price)."""
    try:
        deadline = time.time() + 8.0
        result = None
        while time.time() < deadline:
            result = driver.execute_script(_CLEAR_AND_COUNT_JS)
            if result and result.get("ready"):
                break
            time.sleep(0.15)

        if not result or not result.get("ready"):
            logger.warning("country/region block not found within 8s")
            return False

        remaining = int(result.get("remaining") or 0)
        logger.info(
            "country/region cleared: toggled=%s remaining=%s ladder_visible=%s",
            result.get("toggled"),
            remaining,
            result.get("ladder_visible"),
        )
        return remaining == 0
    except Exception as exc:
        logger.warning("clear country/region failed: %s", exc)
        return False


def country_ladder_price_required(driver) -> bool:
    try:
        return bool(
            driver.execute_script(
                """
                const r = document.getElementById('struct-icbuCountryRegion');
                if (!r) return false;
                let n = 0;
                for (const cb of r.querySelectorAll('input[type=checkbox]')) {
                  const wrap = cb.closest('.next-checkbox-wrapper');
                  const inner = wrap && wrap.querySelector('.next-checkbox');
                  if (inner && inner.classList.contains('checked')) n++;
                  else if (cb.getAttribute('aria-checked') === 'true') n++;
                  else if (cb.checked) n++;
                }
                if (!n) return false;
                const b = document.getElementById('struct-countryLadderPrice');
                return !!(b && b.offsetParent);
                """
            )
        )
    except Exception:
        return False
