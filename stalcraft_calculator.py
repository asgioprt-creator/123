#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STALCRAFT X - Inventory Calculator (PySide6 desktop version)

Сохранение: stalcraft_items.json (рядом со скриптом)
Поддерживаемая функциональность:
- Список предметов с полями id,name,type,quality,enchantment,quantity,buyPrice,sellPrice
- Группировка по name|type|quality|enchantment (разворачивые группы)
- Редактирование quantity, buyPrice, sellPrice, enchantment (группы) в интерфейсе
- Добавление новых предметов (с выбранным количеством -> добавляет несколько записей)
- Удаление предмета / группы
- Копировать/вставить/дублировать (split) элемент
- Сортировка по колонкам
- Экспорт/импорт JSON
- Автосохранение (debounce)
"""

import sys
import json
from pathlib import Path
from functools import partial

from PySide6 import QtCore, QtGui, QtWidgets

# --- Константы и исходные данные
ARTIFACT_QUALITIES = ['Обычный', 'Необычный', 'Особый', 'Редкий', 'Исключительный', 'Легендарный', 'Уникальный']
OTHER_QUALITIES = ['Отмычка', 'Новичок', 'Сталкер', 'Ветеран', 'Мастер', 'Легенда']
ITEM_TYPES = ['Артефакт', 'Оружие', 'Броня', 'Устройство', 'Прочее']

DEFAULT_ITEMS = [
    { 'id': 1, 'name': 'Осколок', 'type': 'Артефакт', 'quality': 'Редкий', 'enchantment': 15, 'quantity': 3, 'buyPrice': 5000, 'sellPrice': 5300 },
    { 'id': 2, 'name': 'Осколок', 'type': 'Артефакт', 'quality': 'Редкий', 'enchantment': 15, 'quantity': 1, 'buyPrice': 5000, 'sellPrice': 5300 },
]

SAVE_FILENAME = Path(__file__).with_name('stalcraft_items.json')

# --- Утилиты форматирования
def format_number(n):
    try:
        n = int(n)
    except Exception:
        n = 0
    s = f"{n:,}".replace(',', ' ')
    return s

def parse_number(s):
    if s is None:
        return 0
    try:
        return int(str(s).replace(' ', '').replace(',', '') or 0)
    except Exception:
        return 0

# --- Главное окно
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("STALCRAFT X — Калькулятор Склада")
        self.resize(1200, 800)

        # Данные
        self.items = self.load_items()
        self.copied_item = None
        self.split_map = {}   # { child_id: parent_id }
        self._programmatic_update = False

        # UI
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)

        # Header (autosave indicator + buttons)
        header_h = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel("Сохранено")
        header_h.addWidget(self.status_label)
        header_h.addStretch()

        btn_save = QtWidgets.QPushButton("💾 Скачать")
        btn_save.clicked.connect(self.export_json)

        btn_load = QtWidgets.QPushButton("⬇️ Загрузить")
        btn_load.clicked.connect(self.import_json)

        btn_paste = QtWidgets.QPushButton("📋 Вставить")
        btn_paste.clicked.connect(self.paste_item)
        btn_paste.setEnabled(False)
        self.btn_paste = btn_paste

        header_h.addWidget(btn_paste)
        header_h.addWidget(btn_load)
        header_h.addWidget(btn_save)
        main_layout.addLayout(header_h)

        # Split: left form / right table
        split = QtWidgets.QHBoxLayout()
        main_layout.addLayout(split)

        # Left panel
        left_frame = QtWidgets.QFrame()
        left_frame.setFixedWidth(360)
        left_layout = QtWidgets.QVBoxLayout(left_frame)
        left_layout.setSpacing(12)

        # Summary blocks
        self.lbl_total_buy = QtWidgets.QLabel()
        self.lbl_total_sell = QtWidgets.QLabel()
        self.lbl_profit = QtWidgets.QLabel()
        self.update_totals_labels()

        left_layout.addWidget(self._make_summary("💰 Покупка", self.lbl_total_buy))
        left_layout.addWidget(self._make_summary("🟩 Продажа", self.lbl_total_sell))
        left_layout.addWidget(self._make_summary("📈 Прибыль", self.lbl_profit))

        # Add item form
        form_box = QtWidgets.QGroupBox("Добавить предмет")
        form_layout = QtWidgets.QFormLayout(form_box)

        self.input_name = QtWidgets.QLineEdit()
        self.input_type = QtWidgets.QComboBox()
        self.input_type.addItems(ITEM_TYPES)
        self.input_quality = QtWidgets.QComboBox()
        self.input_quality.addItems(ARTIFACT_QUALITIES)
        self.input_ench = QtWidgets.QSpinBox()
        self.input_ench.setRange(0, 15)
        self.input_qty = QtWidgets.QSpinBox()
        self.input_qty.setRange(1, 9999)
        self.input_qty.setValue(1)
        self.input_buy = QtWidgets.QLineEdit("0")
        self.input_sell = QtWidgets.QLineEdit("0")

        self.input_type.currentTextChanged.connect(self.on_type_changed)
        self.input_buy.setValidator(QtGui.QRegExpValidator(QtCore.QRegExp(r'[0-9\s,]*')))
        self.input_sell.setValidator(QtGui.QRegExpValidator(QtCore.QRegExp(r'[0-9\s,]*')))

        form_layout.addRow("Название", self.input_name)
        form_layout.addRow("Тип", self.input_type)
        form_layout.addRow("Редкость", self.input_quality)

        hrow = QtWidgets.QHBoxLayout()
        hrow.addWidget(self.input_ench)
        hrow.addWidget(self.input_qty)
        form_layout.addRow("Заточка / Кол-во", hrow)

        form_layout.addRow("Покупка (₽)", self.input_buy)
        form_layout.addRow("Продажа (₽)", self.input_sell)

        btn_add = QtWidgets.QPushButton("Добавить")
        btn_add.clicked.connect(self.add_item_from_form)
        form_layout.addRow(btn_add)

        left_layout.addWidget(form_box)
        left_layout.addStretch()
        split.addWidget(left_frame)

        # Right panel (tree)
        right_frame = QtWidgets.QFrame()
        right_layout = QtWidgets.QVBoxLayout(right_frame)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(11)
        self.tree.setHeaderLabels([
            "Название", "Тип", "Редкость", "Заточка",
            "Кол-во", "Покупка", "Сумма покупки",
            "Продажа", "Сумма продажи", "Прибыль", "Действия"
        ])
        self.tree.header().setSectionsClickable(True)
        self.tree.setRootIsDecorated(False)
        self.tree.itemChanged.connect(self.on_item_changed)
        self.tree.setUniformRowHeights(False)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setSortingEnabled(True)
        right_layout.addWidget(self.tree)
        split.addWidget(right_frame)

        # Style
        self.apply_styles()

        # Autosave timer (debounce)
        self.save_timer = QtCore.QTimer()
        self.save_timer.setInterval(700)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.autosave)

        # initial populate
        self.refresh_tree()

    def _make_summary(self, title, widget_label):
        w = QtWidgets.QWidget()
        l = QtWidgets.QVBoxLayout(w)
        lab = QtWidgets.QLabel(title)
        lab.setStyleSheet("color: #aaa; font-weight: 700;")
        widget_label.setStyleSheet("color: #ffd700; font-size: 18px; font-weight: bold;")
        l.addWidget(lab)
        l.addWidget(widget_label)
        return w

    def apply_styles(self):
        # Dark + gold style (approx)
        self.setStyleSheet("""
            QMainWindow { background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1, stop:0 #101027, stop:1 #0f1738); color: #fff; }
            QTreeWidget { background: rgba(30,30,50,0.9); border: 3px solid #ffd700; border-radius: 8px; }
            QHeaderView::section { background: rgba(255,215,0,0.12); color: #ffd700; padding: 8px; }
            QGroupBox { background: rgba(0,0,0,0.4); border: 2px solid rgba(255,215,0,0.25); border-radius: 8px; padding: 8px; color: #ddd; }
            QPushButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #ffd700, stop:1 #ffed4e); color: #000; border-radius:6px; padding:6px; }
            QPushButton:disabled { opacity: 0.6; }
            QLineEdit, QComboBox, QSpinBox { background: rgba(255,255,255,0.06); color: #ffd700; border: 2px solid #ffd700; padding: 6px; border-radius:6px; }
        """)

    # --- Data management
    def load_items(self):
        try:
            if SAVE_FILENAME.exists():
                with open(SAVE_FILENAME, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
            return DEFAULT_ITEMS.copy()
        except Exception:
            return DEFAULT_ITEMS.copy()

    def save_items_to_disk(self):
        try:
            with open(SAVE_FILENAME, 'w', encoding='utf-8') as f:
                json.dump(self.items, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("Save error:", e)

    def autosave(self):
        self.save_items_to_disk()
        self.status_label.setText("Сохранено")

    def mark_dirty(self):
        self.status_label.setText("Сохранение...")
        self.save_timer.start()

    # --- UI / Tree refresh
    def group_items(self):
        groups = {}
        for item in self.items:
            key = f"{item['name']}|{item['type']}|{item['quality']}|{item['enchantment']}"
            groups.setdefault(key, []).append(item)
        return groups

    def refresh_tree(self):
        self._programmatic_update = True
        self.tree.clear()
        groups = self.group_items()
        for key, group_items in groups.items():
            name, typ, quality, ench = key.split('|')
            total_qty = sum(i['quantity'] for i in group_items)
            total_buy = sum(i['quantity'] * i['buyPrice'] for i in group_items)
            total_sell = sum(i['quantity'] * i['sellPrice'] for i in group_items)
            profit = total_sell - total_buy

            group_item = QtWidgets.QTreeWidgetItem(self.tree)
            group_item.setText(0, name)
            group_item.setText(1, typ)
            group_item.setText(2, quality)
            group_item.setText(3, f"+{ench}")
            group_item.setText(4, str(total_qty))
            group_item.setText(6, f"{format_number(total_buy)} ₽")
            group_item.setText(8, f"{format_number(total_sell)} ₽")
            group_item.setText(9, f"{('+' if profit>=0 else '')}{format_number(profit)} ₽")
            group_item.setData(0, QtCore.Qt.UserRole, {"group": key})

            # actions widget for group (delete)
            btn_widget = QtWidgets.QWidget()
            h = QtWidgets.QHBoxLayout(btn_widget)
            h.setContentsMargins(0, 0, 0, 0)
            btn_delete = QtWidgets.QPushButton("🗑️")
            btn_delete.setToolTip("Удалить группу")
            btn_delete.clicked.connect(partial(self.delete_group, key))
            h.addWidget(btn_delete)
            h.addStretch()
            self.tree.setItemWidget(group_item, 10, btn_widget)

            # add child rows
            for it in group_items:
                child = QtWidgets.QTreeWidgetItem(group_item)
                child.setText(3, f"+{it['enchantment']}")
                child.setText(4, str(it['quantity']))
                child.setText(5, f"{format_number(it['buyPrice'])} ₽")
                child.setText(6, f"{format_number(it['quantity'] * it['buyPrice'])} ₽")
                child.setText(7, f"{format_number(it['sellPrice'])} ₽")
                child.setText(8, f"{format_number(it['quantity'] * it['sellPrice'])} ₽")
                profit_i = it['quantity'] * it['sellPrice'] - it['quantity'] * it['buyPrice']
                child.setText(9, f"{('+' if profit_i>=0 else '')}{format_number(profit_i)} ₽")
                child.setData(0, QtCore.Qt.UserRole, {"id": it['id']})
                # Make quantity, buyPrice, sellPrice editable (we edit by double click)
                child.setFlags(child.flags() | QtCore.Qt.ItemIsEditable)
                # Name/Type/Quality left empty for children
                child.setText(0, "")
                child.setText(1, "")
                child.setText(2, "")

                # actions: copy, duplicate, delete
                btnw = QtWidgets.QWidget()
                hh = QtWidgets.QHBoxLayout(btnw)
                hh.setContentsMargins(0,0,0,0)
                bcopy = QtWidgets.QPushButton("📋")
                bcopy.setToolTip("Копировать")
                bcopy.clicked.connect(partial(self.copy_item_by_id, it['id']))
                bdup = QtWidgets.QPushButton("➕")
                bdup.setToolTip("Дублировать (split)")
                bdup.clicked.connect(partial(self.duplicate_subitem, it['id']))
                bdel = QtWidgets.QPushButton("🗑️")
                bdel.setToolTip("Удалить")
                bdel.clicked.connect(partial(self.delete_item_by_id, it['id']))
                hh.addWidget(bcopy)
                hh.addWidget(bdup)
                hh.addWidget(bdel)
                hh.addStretch()
                self.tree.setItemWidget(child, 10, btnw)

            group_item.setExpanded(False)

        self.tree.resizeColumnToContents(0)
        self.update_totals_labels()
        self._programmatic_update = False

    # --- Actions (add/delete/modify)
    def add_item_from_form(self):
        name = self.input_name.text().strip()
        if not name:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Введите название предмета")
            return
        typ = self.input_type.currentText()
        quality = self.input_quality.currentText()
        ench = int(self.input_ench.value())
        qty = int(self.input_qty.value())
        buy = parse_number(self.input_buy.text())
        sell = parse_number(self.input_sell.text())

        base_id = max([it['id'] for it in self.items] + [0])
        new_items = []
        for i in range(qty):
            base_id += 1
            new_items.append({
                "id": base_id,
                "name": name,
                "type": typ,
                "quality": quality,
                "enchantment": ench,
                "quantity": 1,
                "buyPrice": buy,
                "sellPrice": sell
            })
        self.items.extend(new_items)
        self.mark_dirty()
        self.refresh_tree()
        # reset form
        self.input_name.clear()
        self.input_type.setCurrentIndex(0)
        self.input_quality.setCurrentIndex(0)
        self.input_ench.setValue(0)
        self.input_qty.setValue(1)
        self.input_buy.setText("0")
        self.input_sell.setText("0")

    def delete_item_by_id(self, item_id):
        self.items = [it for it in self.items if it['id'] != item_id]
        # also drop split_map entries referencing it
        self.split_map = {k:v for k,v in self.split_map.items() if k!=item_id and v!=item_id}
        self.mark_dirty()
        self.refresh_tree()

    def delete_group(self, group_key):
        groups = self.group_items()
        group_items = groups.get(group_key, [])
        ids = {it['id'] for it in group_items}
        self.items = [it for it in self.items if it['id'] not in ids]
        self.mark_dirty()
        self.refresh_tree()

    def copy_item_by_id(self, item_id):
        it = next((x for x in self.items if x['id']==item_id), None)
        if it:
            self.copied_item = it.copy()
            self.btn_paste.setEnabled(True)
            self.status_label.setText("Скопировано")
        else:
            self.copied_item = None
            self.btn_paste.setEnabled(False)

    def paste_item(self):
        if not self.copied_item:
            return
        new_id = max([i['id'] for i in self.items] + [0]) + 1
        new = self.copied_item.copy()
        new['id'] = new_id
        self.items.append(new)
        self.mark_dirty()
        self.refresh_tree()

    def duplicate_subitem(self, item_id):
        it = next((x for x in self.items if x['id']==item_id), None)
        if not it:
            return
        new_id = max([i['id'] for i in self.items] + [0]) + 1
        new_item = it.copy()
        new_item['id'] = new_id
        new_item['quantity'] = 0
        new_item['sellPrice'] = 0
        self.items.append(new_item)
        self.split_map[new_id] = item_id
        self.mark_dirty()
        self.refresh_tree()

    # --- Editing: map item changes from tree to data
    def on_item_changed(self, tree_item, col):
        if self._programmatic_update:
            return
        data = tree_item.data(0, QtCore.Qt.UserRole)
        if not data:
            return
        if isinstance(data, dict) and 'id' in data:
            item_id = data['id']
            try:
                it = next(x for x in self.items if x['id']==item_id)
            except StopIteration:
                return
            changed = False
            # quantity
            txt_qty = tree_item.text(4).strip()
            if txt_qty != str(it['quantity']):
                try:
                    newq = int(txt_qty)
                except:
                    newq = it['quantity']
                if newq != it['quantity']:
                    parent_id = self.split_map.get(item_id)
                    if parent_id:
                        parent = next((x for x in self.items if x['id']==parent_id), None)
                        if parent:
                            diff = newq - it['quantity']
                            parent['quantity'] = max(0, parent['quantity'] - diff)
                    it['quantity'] = newq
                    changed = True

            # buyPrice (column 5)
            txt_buy = tree_item.text(5).replace('₽','').strip()
            buy_val = parse_number(txt_buy)
            if buy_val != it['buyPrice']:
                it['buyPrice'] = buy_val
                changed = True

            # sellPrice (column 7)
            txt_sell = tree_item.text(7).replace('₽','').strip()
            sell_val = parse_number(txt_sell)
            if sell_val != it['sellPrice']:
                it['sellPrice'] = sell_val
                changed = True

            if changed:
                self.mark_dirty()
                self.refresh_tree()

    # --- Import / Export
    def export_json(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Сохранить как", str(Path.home() / "stalcraft_inventory.json"), "JSON files (*.json)")
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.items, f, ensure_ascii=False, indent=2)
            QtWidgets.QMessageBox.information(self, "Готово", "Файл сохранён")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Ошибка", str(e))

    def import_json(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Открыть файл", str(Path.home()), "JSON files (*.json)")
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                self.items = data
                self.mark_dirty()
                self.refresh_tree()
                QtWidgets.QMessageBox.information(self, "Готово", "Данные загружены")
            else:
                QtWidgets.QMessageBox.warning(self, "Ошибка", "Неправильный формат файла")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Ошибка", str(e))

    # --- Additional interactions (double click quality/enchantment)
    def mouseDoubleClickEvent(self, ev):
        item = self.tree.itemAt(ev.position().toPoint()) if hasattr(ev, 'position') else self.tree.itemAt(ev.pos())
        if not item:
            return super().mouseDoubleClickEvent(ev)

        cur_item = self.tree.currentItem()
        cur_col = self.tree.currentColumn()
        if not cur_item:
            return super().mouseDoubleClickEvent(ev)
        data = cur_item.data(0, QtCore.Qt.UserRole)
        if data and isinstance(data, dict) and 'group' in data:
            col = self._get_column_at_pos(ev)
            if col == 3:
                self.edit_group_enchantment(data['group'])
                return
            if col == 2:
                self.edit_group_quality(data['group'])
                return
        return super().mouseDoubleClickEvent(ev)

    def _get_column_at_pos(self, ev):
        pos = ev.position().toPoint() if hasattr(ev, 'position') else ev.pos()
        header = self.tree.header()
        x = pos.x()
        accum = 0
        for c in range(self.tree.columnCount()):
            w = header.sectionSize(c)
            if x < accum + w:
                return c
            accum += w
        return -1

    def edit_group_enchantment(self, group_key):
        groups = self.group_items()
        group = groups.get(group_key, [])
        if not group:
            return
        cur_ench = int(group[0]['enchantment'])
        val, ok = QtWidgets.QInputDialog.getInt(self, "Изменить заточку группы", "Заточка (+):", value=cur_ench, min=0, max=15)
        if ok:
            for it in group:
                it['enchantment'] = val
            self.mark_dirty()
            self.refresh_tree()

    def edit_group_quality(self, group_key):
        groups = self.group_items()
        group = groups.get(group_key, [])
        if not group:
            return
        typ = group[0]['type']
        choices = ARTIFACT_QUALITIES if typ == 'Артефакт' else OTHER_QUALITIES
        cur_q = group[0]['quality']
        val, ok = QtWidgets.QInputDialog.getItem(self, "Изменить редкость группы", "Редкость:", choices, current=choices.index(cur_q) if cur_q in choices else 0, editable=False)
        if ok:
            for it in group:
                it['quality'] = val
            self.mark_dirty()
            self.refresh_tree()
            def on_type_changed(self, text):
    """
    Обновляет выпадающий список редкостей при смене типа предмета.
    Вставьте этот метод внутрь класса MainWindow (например после apply_styles).
    """
    # Сохраним текущую выбранную редкость, если она есть
    current = self.input_quality.currentText() if self.input_quality.count() > 0 else None

    # Блокируем сигналы на время изменения, чтобы избежать рекурсии
    self.input_quality.blockSignals(True)
    self.input_quality.clear()

    qualities = ARTIFACT_QUALITIES if text == 'Артефакт' else OTHER_QUALITIES
    self.input_quality.addItems(qualities)

    # Восстановим прежний выбор, если он присутствует в новом списке
    if current and current in qualities:
        self.input_quality.setCurrentIndex(qualities.index(current))
    else:
        self.input_quality.setCurrentIndex(0)

    self.input_quality.blockSignals(False)

    # --- Helpers
    def update_totals_labels(self):
        total_buy = sum(it['quantity'] * it['buyPrice'] for it in self.items)
        total_sell = sum(it['quantity'] * it['sellPrice'] for it in self.items)
        profit = total_sell - total_buy
        self.lbl_total_buy.setText(f"{format_number(total_buy)} ₽")
        self.lbl_total_sell.setText(f"{format_number(total_sell)} ₽")
        self.lbl_profit.setText(( "+" if profit>=0 else "" ) + f"{format_number(profit)} ₽")
        if profit >= 0:
            self.lbl_profit.setStyleSheet("color: #00ff00; font-size:18px; font-weight:bold;")
        else:
            self.lbl_profit.setStyleSheet("color: #ff4444; font-size:18px; font-weight:bold;")

    # Override closeEvent to save
    def closeEvent(self, event):
        self.save_items_to_disk()
        event.accept()

# --- Запуск приложения
def main():
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
