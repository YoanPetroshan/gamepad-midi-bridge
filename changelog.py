"""What's new in each version, shown after an update (and from Settings).

Newest first. Each entry: version → (English items, Bulgarian items).
Add an entry here with every release; the GitHub release notes can be copied from it.
"""
from __future__ import annotations

import i18n
from updater import parse_version

CHANGES: dict[str, tuple[list[str], list[str]]] = {
    "1.6.0": (
        [
            "**The version is always visible**, bottom right (ⓘ Xbox MIDI Bridge 1.6.0). Click it for the "
            "**About window**: version, Check for updates, What's new, and info for support.",
            "**Send feedback from the app:** write a wish, a problem or a question; the app opens GitHub "
            "with the text already filled in (you need a free GitHub account, and the text is public). "
            "Wishes can be voted for with a 👍, and everyone can see them with “See wishes & problems”.",
        ],
        [
            "**Версията се вижда винаги**, долу вдясно (ⓘ Xbox MIDI Bridge 1.6.0). Цъкни върху нея за "
            "**прозореца „За приложението“**: версия, Провери за обновления, Какво е новото и информация "
            "за поддръжка.",
            "**Изпращане на отзив от приложението:** напиши желание, проблем или въпрос; приложението "
            "отваря GitHub с вече попълнен текст (нужен е безплатен акаунт в GitHub, а текстът е публичен). "
            "Желанията се гласуват с 👍 и всеки ги вижда с „Виж желания и проблеми“.",
        ],
    ),
    "1.5.0": (
        [
            "**Language button** in the toolbar (🌐 BG / 🌐 EN): one click switches the whole interface "
            "between English and Bulgarian, instantly, **without restarting**: the controller, MIDI and "
            "your layers keep running, nothing is interrupted.",
        ],
        [
            "**Бутон за език** в лентата (🌐 BG / 🌐 EN): с един клик целият интерфейс минава от български "
            "на английски и обратно, веднага и **без рестарт**: контролерът, MIDI и слоевете ти работят "
            "непрекъснато, нищо не се прекъсва.",
        ],
    ),
    "1.4.0": (
        [
            "**Modifiers can be Toggle:** press once to switch the layer on, press again to switch "
            "it off (Mode → Toggle), or keep the old behaviour, Hold.",
            "**The diagram follows the controller:** while you hold a modifier it shows that layer and "
            "goes back to the base layer when you let go. New checkbox **Keep layer** keeps a layer on "
            "screen for editing.",
            "**New layers fill themselves:** when a button becomes a modifier, every unassigned "
            "button of the new layer gets a free Note number right away (the next channel when a "
            "channel runs out). Change any of them later. Can be switched off in Settings.",
            "**Number fields without arrows:** click the number and type a new one, or open the "
            "list of all values. Values already in use show which button of which layer uses them.",
        ],
        [
            "**Модификаторите могат да са Toggle:** натискаш веднъж за включване на слоя и пак за "
            "изключване (Режим → Toggle), или оставяш старото поведение, Задържане.",
            "**Схемата следва контролера:** докато държиш модификатор, показва неговия слой и се "
            "връща на основния, когато го пуснеш. Нова отметка **Задръж слоя** оставя слой на екрана "
            "за редактиране.",
            "**Новите слоеве се попълват сами:** когато бутон стане модификатор, всеки свободен "
            "бутон на новия слой получава веднага свободен Note номер (следващ канал, когато каналът "
            "свърши). После променяш който искаш. Изключва се от Настройки.",
            "**Полета с числа без стрелки:** цъкаш върху числото и пишеш ново или отваряш списъка "
            "с всички стойности. Заетите показват кой бутон от кой слой ги ползва.",
        ],
    ),
    "1.3.1": (
        [
            "**Fixed: PlayStation controllers over Bluetooth.** The DualSense / DualShock 4 is now "
            "switched to its full report mode, so the **Mic (mute) button**, the touchpad position, "
            "the gyro and the light bar work over Bluetooth too (before, they only worked over USB).",
        ],
        [
            "**Поправено: PlayStation контролери по Bluetooth.** DualSense / DualShock 4 вече се "
            "превключва в пълен режим, така че **бутонът Mic (заглушаване)**, позицията на тъчпада, "
            "жироскопът и светлинната лента работят и по Bluetooth (преди работеха само по USB).",
        ],
    ),
    "1.3.0": (
        [
            "**Automatic updates:** the app checks GitHub for a new version at startup and can "
            "download, verify and install it for you (Settings → Check for updates).",
            "**What's new** is shown after every update, and from Settings at any time.",
            "`--check-update` on the command line prints the installed and the latest version.",
        ],
        [
            "**Автоматични обновления:** при старт приложението проверява в GitHub за нова версия и "
            "може само да я изтегли, провери и инсталира (Настройки → Провери за обновления).",
            "**„Какво е новото“** се показва след всяко обновяване, а и по всяко време от Настройки.",
            "`--check-update` от командния ред показва инсталираната и последната версия.",
        ],
    ),
    "1.2.0": (
        [
            "**PlayStation controllers (DualSense / DualShock 4)** with their own diagram and names.",
            "Touchpad click, and the touchpad surface as a trackpad (drag) or an XY pad.",
            "Gyro aiming while a “Gyro” button is held; the light bar shows the active layer.",
            "**Sensitivity** for every stick, touchpad and gyro axis.",
            "Absolute sticks can **hold their position** when released, with pick-up (no jumps).",
            "Axes on the same CC share one value: stick, touchpad and gyro switch without jumps.",
        ],
        [
            "**PlayStation контролери (DualSense / DualShock 4)** със собствена схема и имена.",
            "Тъчпад клик, а повърхността на тъчпада като тракпад (плъзгане) или XY пад.",
            "Насочване с жироскоп, докато е задържан бутон „Жиро“; лентата показва активния слой.",
            "**Чувствителност** за всеки стик, тъчпад и жироскоп.",
            "Абсолютните стикове могат да **задържат позицията** при пускане, с поемане (без скок).",
            "Осите на един и същ CC имат обща стойност: стик, тъчпад и жироскоп се сменят без скок.",
        ],
    ),
    "1.1.0": (
        [
            "Modifiers and layers (key combinations), L3/R3 glide Pan/Tilt back to center.",
            "English and Bulgarian interface.",
        ],
        [
            "Модификатори и слоеве (клавишни комбинации), L3/R3 връщат Pan/Tilt плавно в центъра.",
            "Интерфейс на английски и български.",
        ],
    ),
}


def items(version: str) -> list[str]:
    en, bg = CHANGES.get(version, ([], []))
    return bg if i18n.LANG == "bg" else en


def markdown_since(previous: str | None, current: str) -> str:
    """Markdown for every version after `previous` up to and including `current`."""
    out = []
    for v in sorted(CHANGES, key=parse_version, reverse=True):
        if parse_version(v) > parse_version(current):
            continue
        if previous and parse_version(v) <= parse_version(previous):
            continue
        out.append(f"### {v}\n\n" + "\n".join(f"- {i}" for i in items(v)))
        if not previous:
            break  # only the current version
    return "\n\n".join(out)
