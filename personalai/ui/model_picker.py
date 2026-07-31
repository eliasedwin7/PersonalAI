"""Shared helpers for Ollama model pickers.

The combo boxes stay editable for custom/API model names, but recommended
Ollama models can be shown even before they are installed.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox

DOWNLOAD_SUFFIX = " [download]"
RECOMMENDED_SUFFIX = " [recommended]"
MODEL_ROLE = Qt.ItemDataRole.UserRole


def populate_model_combo(
    combo: QComboBox,
    current_value: str,
    installed_models: list[str],
    recommended_models: list[str],
) -> None:
    current_value = clean_model_text(current_value)
    installed = [clean_model_text(model) for model in installed_models if clean_model_text(model)]
    recommended = [
        clean_model_text(model) for model in recommended_models if clean_model_text(model)
    ]
    installed_set = set(installed)
    recommended_set = set(recommended)
    models = list(dict.fromkeys([current_value, *recommended, *installed]))

    combo.clear()
    for model in models:
        if not model:
            continue
        label = model
        if model in recommended_set:
            label += RECOMMENDED_SUFFIX if model in installed_set else DOWNLOAD_SUFFIX
        combo.addItem(label, model)
        index = combo.count() - 1
        if model in recommended_set and model not in installed_set:
            combo.setItemData(
                index,
                f"Recommended for this hardware profile. Nexus will download {model} with Ollama when selected.",
                Qt.ItemDataRole.ToolTipRole,
            )
        elif model in recommended_set:
            combo.setItemData(index, "Recommended for this hardware profile.", Qt.ItemDataRole.ToolTipRole)

    index = find_model_index(combo, current_value)
    if index >= 0:
        combo.setCurrentIndex(index)
    else:
        combo.setCurrentText(current_value)


def selected_model(combo: QComboBox) -> str:
    index = combo.currentIndex()
    if index >= 0 and combo.currentText() == combo.itemText(index):
        data = combo.itemData(index, MODEL_ROLE)
        if isinstance(data, str) and data.strip():
            return data.strip()
    return clean_model_text(combo.currentText())


def clean_model_text(text: str) -> str:
    cleaned = text.strip()
    for suffix in (DOWNLOAD_SUFFIX, RECOMMENDED_SUFFIX):
        if cleaned.endswith(suffix):
            return cleaned[:-len(suffix)].strip()
    return cleaned


def find_model_index(combo: QComboBox, model: str) -> int:
    model = clean_model_text(model)
    for index in range(combo.count()):
        if combo.itemData(index, MODEL_ROLE) == model:
            return index
    return -1
