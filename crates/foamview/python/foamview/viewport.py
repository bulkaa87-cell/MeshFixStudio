"""The «3D» view widget of MeshFix Studio and OpenFOAM Studio.

SHARED CODE: Viewport was the class foam_studio.Viewport of OpenFOAM
Studio, without its CFD layers (the domain, the refinement boxes, the point
in the flow, the flow arrow, the rotor axis, the results). OpenFOAM Studio
keeps those in a subclass. FlowLayout was fs_panels.FlowLayout.

The view draws with foamview.level.select_level(): foamview on a GPU, on a
software adapter, VTK (pyvistaqt), or the foamview CPU renderer.

The inline comments are in Ukrainian: they come from the source modules.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_API", "pyside6")

import numpy as np
import pyvista as pv
from PySide6 import QtCore, QtWidgets
from pyvistaqt import QtInteractor

from meshfix import check as geo
from meshfix.i18n import tr

COL_BODY = "#b9c4cf"
COL_HOLE = "#ff2d2d"
COL_FLIP = "#e252d8"      # грані вивернутих частин
COL_NM = "#ffd23f"        # non-manifold ребра
COL_DEGEN = "#5ef08a"     # вироджені трикутники
COL_SPOT = "#00e5ff"      # куди підлетіла камера

PROBLEM_LAYERS = {
    "holes": ("Holes", COL_HOLE,
              "Open edges. A hole larger than a cell becomes a channel "
              "into the body. “Repair” closes it (meshfix method)."),
    "flip": ("Flipped", COL_FLIP,
             "Faces of parts whose normals point inward. They break the "
             "“inside/outside” checks in snappy. “Repair” flips them "
             "back."),
    "nm": ("Non-manifold", COL_NM,
           "Edges shared by more than two triangles — traces of parts "
           "that cut into each other. Castellation tolerates this; "
           "feature edges are fixed by includedAngle 170 or a Boolean "
           "union in CAD."),
    "degen": ("Degenerate", COL_DEGEN,
              "Triangles with zero area. “Repair” removes them."),
}

_LAYER_STYLE = {
    "holes": dict(color=COL_HOLE, line_width=6, render_lines_as_tubes=True),
    "nm": dict(color=COL_NM, line_width=3),
    "flip": dict(color=COL_FLIP, opacity=0.9, show_edges=False),
    "degen": dict(color=COL_DEGEN, point_size=13,
                  render_points_as_spheres=True),
}


class FlowLayout(QtWidgets.QLayout):
    """Рядок віджетів, що ПЕРЕНОСИТЬСЯ, як текст, коли ширини бракує.

    Звичайний QHBoxLayout вимагає місця під усі віджети разом, і саме так
    нижній рядок вʼюпорту (десять позначок і шість кнопок) не давав вікну
    стати вужчим за ~1750 px: на екрані з масштабом 125 % вікно вилазило за
    край, а повзунок між панелями впирався й не рухався. Тут мінімум — це
    найширший ОДИН віджет, а решта лягає на наступні рядки.
    """

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items: list = []
        self._gap = spacing

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return QtCore.Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._place(QtCore.QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QtCore.QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QtCore.QSize(m.left() + m.right(), m.top() + m.bottom())

    def _place(self, rect, apply: bool) -> int:
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line = area.x(), area.y(), 0
        for item in self._items:
            if item.widget() is not None and item.widget().isHidden():
                continue
            hint = item.sizeHint()
            if x > area.x() and x + hint.width() > area.right() + 1:
                x, y, line = area.x(), y + line + self._gap, 0
            if apply:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), hint))
            x += hint.width() + self._gap
            line = max(line, hint.height())
        return y + line - rect.y() + m.bottom()


class Viewport(QtWidgets.QWidget):
    """The «3D» view: the model, its problem layers, the ruler and the view
    buttons. A program adds its own layers in a subclass: EXTRA_CHECKS
    gives more check boxes (OpenFOAM Studio: the domain, the refinement
    boxes, the point in the flow, the flow direction), and its methods add
    the actors (self.plotter.add_mesh, self.actors[key]).
    """

    # (key, label, checked) of the check boxes under the view.
    BASE_CHECKS = (("body", "Model", True),
                   ("holes", "Holes", True),
                   ("flip", "Flipped", True),
                   ("nm", "Non-manifold", False),
                   ("degen", "Degenerate", True))
    EXTRA_CHECKS: tuple = ()
    END_CHECKS = (("ruler", "Ruler", False),)
    # The «All» button (fit the whole scene, not only the model).
    FIT_ALL = True

    # «До моделі» тут лише ПРОСЯТЬ. Камеру ставить вікно: вʼюпортів два
    # (3D і результати), а команда одна — на обидва.
    to_model_requested = QtCore.Signal()
    # Хто малює «3D» (текст для рядка стану, причина вибору) — і коли
    # віджет сам перейшов на запасний рівень під час роботи.
    level_changed = QtCore.Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.plotter = self._make_plotter()
        # Stretch 1: ALL the free height goes to the view. Without it, the
        # free height went to the view AND to the controls row: the
        # foamview widget has the "Preferred" policy (the VTK widget has
        # "Expanding"), so the layout shared the space. The FlowLayout
        # puts the controls at the top of its row, and the remainder below
        # the controls was an empty grey area (T13, 2026-11-10).
        lay.addWidget(self.plotter.interactor, 1)
        self.plotter.set_background("#22262b", top="#3a4149")
        self.plotter.add_axes(line_width=2)
        self.actors: dict[str, object] = {}
        self._body_bounds: tuple | None = None
        self._label: dict[str, str] = {}

        # Рядок, що ПЕРЕНОСИТЬСЯ: у звичайному рядку ці шістнадцять віджетів
        # не давали вікну стати вужчим за ~1750 px (див. panels.FlowLayout).
        bar_box = QtWidgets.QWidget()
        policy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred,
                                       QtWidgets.QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        bar_box.setSizePolicy(policy)
        bar = FlowLayout(bar_box, spacing=6)
        bar.setContentsMargins(6, 2, 6, 4)
        self.chk = {}
        for key, label, default in (self.BASE_CHECKS + self.EXTRA_CHECKS
                                    + self.END_CHECKS):
            c = QtWidgets.QCheckBox(label)
            c.setChecked(default)
            if key == "ruler":
                # Лінійку не ховаємо, а БУДУЄМО на вимогу: її побудова
                # чіпає камеру (див. show_ruler), тож тримати її готовою
                # про всяк випадок дорого.
                c.toggled.connect(lambda v: self.show_ruler()
                                  if v else self._drop("ruler"))
            else:
                c.toggled.connect(lambda v, k=key: self.set_visible(k, v))
            bar.addWidget(c)
            self.chk[key] = c
            self._label[key] = label
        for key in PROBLEM_LAYERS:
            self.set_problem(key, 0, "")
        for label, view in (("Iso", "iso"), ("X", "yz"), ("Y", "xz"), ("Z", "xy")):
            b = QtWidgets.QPushButton(label)
            b.setFixedWidth(38)
            b.clicked.connect(lambda _=False, v=view: self.set_view(v))
            bar.addWidget(b)
        self.btn_spot = QtWidgets.QPushButton("Next Problem ▸")
        self.btn_spot.setToolTip(
            "Fly to the next hole, flipped part or degenerate triangle — "
            "largest first")
        self.btn_spot.setEnabled(False)
        bar.addWidget(self.btn_spot)
        # Колись тут було «Модель» — так само, як галочка зліва, що ховає
        # тіло. Дві різні речі під одним словом в одній смузі.
        self.btn_fit = QtWidgets.QPushButton("Fit to model")
        self.btn_fit.setToolTip(
            "Camera fits the model in ALL viewports: both here and in "
            "the results. The side you look from stays the same. Ctrl+0")
        self.btn_fit.clicked.connect(lambda: self.to_model_requested.emit())
        bar.addWidget(self.btn_fit)
        self.btn_fit_all = QtWidgets.QPushButton("All")
        self.btn_fit_all.setToolTip("Fit the whole domain in the view")
        self.btn_fit_all.clicked.connect(self.fit_all)
        bar.addWidget(self.btn_fit_all)
        self.btn_fit_all.setVisible(self.FIT_ALL)
        lay.addWidget(bar_box)

    def _make_plotter(self):
        """Хто малює вкладку «3D» — ланцюжок fs_view3d.select_level():
        foamview на GPU → foamview на програмному адаптері → VTK → foamview
        на CPU. Вкладка ЗАВЖДИ показує картинку; повільніше — можна.

        Решта класу однакова для всіх: fs_view3d.Plotter розуміє ті самі
        виклики pyvista, що й QtInteractor. FS_3D=gpu|soft|vtk|cpu — примусово.
        """
        self.backend = "vtk"
        self.backend_note = ""
        self.level = None
        try:
            from . import level as fs_view3d
            lv = fs_view3d.select_level()
            if lv.level in ("gpu", "soft"):
                # Кеш каже «цей адаптер малює» — перевірка в ЦЬОМУ процесі
                # (драйвер могли оновити без зміни версії). Не так — кеш
                # геть, VTK зараз, повний перебір — на наступному старті.
                ok, note = fs_view3d.probe(lv)
                if not ok:
                    fs_view3d.forget_level()
                    lv = fs_view3d.Level("vtk", note=f"{lv.text()}: {note}")
            if lv.foamview:
                pl = fs_view3d.Plotter(self, lv, on_level=self._level_changed)
                self.backend = "foamview"
                self._set_level(lv)
                return pl
            self._set_level(lv)
        except Exception as exc:                          # noqa: BLE001
            self.backend_note = str(exc)
        return QtInteractor(self)

    def _set_level(self, lv):
        self.level = lv
        self.backend_note = lv.note
        self.level_changed.emit(lv.text(), lv.note_text())

    def _level_changed(self, lv):
        """Віджет сам перейшов на CPU (GPU відмовив під час роботи)."""
        self._set_level(lv)

    # --- керування акторами ---------------------------------------------

    def _drop(self, key: str):
        if key in self.actors:
            # Шар може бути з КІЛЬКОХ акторів: лінійка це три лінійки по
            # осях плюс підпис. Тому список — не виняток, а звичайний
            # випадок, і обробляти його треба тут, а не в кожному місці.
            item = self.actors[key]
            for a in (item if isinstance(item, list) else [item]):
                try:
                    self.plotter.remove_actor(a, render=False)
                except Exception:
                    pass
            del self.actors[key]

    def set_visible(self, key: str, visible: bool):
        item = self.actors.get(key)
        if item is None:
            return
        for a in (item if isinstance(item, list) else [item]):
            try:
                a.SetVisibility(visible)
            except Exception:
                pass
        try:
            self.plotter.render()
        except Exception:
            pass

    def set_view(self, which: str):
        p = self.plotter
        {"iso": p.view_isometric, "xy": p.view_xy,
         "xz": p.view_xz, "yz": p.view_yz}[which]()

    def show_ruler(self, bounds=None):
        # ВИМКНЕНУ ЛІНІЙКУ НЕ БУДУЄМО ВЗАГАЛІ.
        #
        # Перша версія будувала її на кожен показ тіла й одразу ховала.
        # Виглядало дешево, а коштувало камери: `add_ruler` усередині
        # кличе `add_actor`, той — `reset_camera`, і наближений вид
        # відлітав від кожної зміни ролі чи налаштування деталі.
        # Користувач це помітив, а я ні: я дивився на видимість шару, а
        # не на те, що його побудова робить із камерою.
        if not self.chk["ruler"].isChecked():
            self._drop("ruler")
            return
        self._show_ruler_now(bounds)

    def _show_ruler_now(self, bounds=None):
        """Лінійки по трьох осях і габарит числами.

        НАВІЩО ЧИСЛА, А НЕ ЛИШЕ ЛІНІЇ. Питання, заради якого лінійку й
        просили, — «чи правильно прочиталися одиниці». На нього відповідає
        не вигляд, а розмір: літак має бути близько метра, а не міліметра
        й не кілометра. Тому підпис угорі показує габарит у міліметрах і
        метрах одразу — щоб помилку в тисячу разів було видно з одного
        погляду.

        Підписи ЛАТИНКОЮ й цифрами: у VTK немає кириличного шрифта, і
        українські літери вийшли б квадратиками.
        """
        self._drop("ruler")
        b = tuple(bounds) if bounds else self._body_bounds
        keep = (tuple(self.plotter.camera.position),
                tuple(self.plotter.camera.focal_point),
                float(self.plotter.camera.parallel_scale))
        if not b or b[1] <= b[0]:
            return
        lx, ly, lz = b[1] - b[0], b[3] - b[2], b[5] - b[4]
        # Лінійки ставимо ЗА тілом, а не крізь нього: інакше вони
        # ховаються в моделі й полічити по них нічого не можна.
        pad = 0.06 * max(lx, ly, lz, 1e-9)
        actors = []
        rulers = (
            ((b[0], b[2] - pad, b[4] - pad), (b[1], b[2] - pad, b[4] - pad),
             "X"),
            ((b[1] + pad, b[2], b[4] - pad), (b[1] + pad, b[3], b[4] - pad),
             "Y"),
            ((b[1] + pad, b[2] - pad, b[4]), (b[1] + pad, b[2] - pad, b[5]),
             "Z"),
        )
        for p1, p2, title in rulers:
            try:
                actors.append(self.plotter.add_ruler(
                    p1, p2, title=tr(title), font_size_factor=0.5,
                    label_format="%.3g", number_labels=5))
            except Exception:
                pass
        txt = (f"{lx * 1000:.0f} x {ly * 1000:.0f} x {lz * 1000:.0f} mm"
               f"   =   {lx:.3f} x {ly:.3f} x {lz:.3f} m")
        try:
            actors.append(self.plotter.add_text(
                txt, position="upper_left", font_size=11,
                color="#e8e8e8", name="ruler_text"))
        except Exception:
            pass
        if not actors:
            self.plotter.camera.position = keep[0]
            self.plotter.camera.focal_point = keep[1]
            self.plotter.camera.parallel_scale = keep[2]
            return
        self.actors["ruler"] = actors
        self.set_visible("ruler", self.chk["ruler"].isChecked())
        # ПОВЕРТАЄМО КАМЕРУ ТУДИ, ДЕ ВОНА БУЛА. `add_ruler` не приймає
        # `reset_camera`, тож інакше її не вбережеш: вона скидається
        # всередині, і побачити це можна лише по кадру.
        self.plotter.camera.position = keep[0]
        self.plotter.camera.focal_point = keep[1]
        self.plotter.camera.parallel_scale = keep[2]
        self.plotter.render()

    def show_body(self, mesh, reset=False):
        """Показує тіло. Нормалі мають бути ВЖЕ пораховані.

        `smooth_shading=True` тут стояти не може: pyvista на кожен показ
        перераховує нормалі з `non_manifold_traversal=True`, і на збірці з
        перетинних деталей вивертає кожну сьому грань — вони темніють, і
        модель виглядає рваною, хоч у файлі все гаразд. Готуємо нормалі
        самі (`geo.display_mesh`), а тут лише малюємо.
        """
        self._drop("body")
        if mesh is None:
            # Тіла нема — нема й куди підлітати. Без цього «До моделі» йшла
            # б туди, де тіло стояло востаннє.
            self._body_bounds = None
            self.plotter.render()
            return
        if "Normals" not in mesh.point_data:
            mesh = geo.display_mesh(mesh)
        self.actors["body"] = self.plotter.add_mesh(
            mesh, color=COL_BODY, smooth_shading=False, specular=0.3,
            show_edges=False, name="body", reset_camera=False)
        self.set_visible("body", self.chk["body"].isChecked())
        self._body_bounds = tuple(mesh.bounds)
        # Лінійка живе разом із тілом: габарит міняється від кожного
        # повороту, зсуву й зміни одиниць, і стара лінійка біля нового
        # тіла брехала б упевнено.
        self.show_ruler()
        if reset:
            self.fit_body()
        self.plotter.render()

    @property
    def has_model(self) -> bool:
        """Чи є в сцені тіло, до якого можна підлетіти."""
        return self._body_bounds is not None

    def fit_body(self):
        """Вписує в кадр МОДЕЛЬ, а не всю сцену.

        Домен більший за тіло разів у пʼятнадцять, тому reset_camera() без
        обмежень робить модель цяткою на пів екрана порожнечі — і поворот на
        90° стає візуально непомітним.
        """
        if self._body_bounds is not None:
            self.plotter.reset_camera(bounds=self._body_bounds)
        else:
            self.plotter.reset_camera()
        # Інакше наступний add_mesh знову вважатиме камеру «невстановленою»
        # і сам перескочить на межі всієї сцени.
        self.plotter.renderer.camera_set = True
        self.plotter.render()

    def fit_all(self):
        self.plotter.reset_camera()
        self.plotter.render()

    def look_at(self, point, radius: float, outward=None):
        """Підлітає до точки, по змозі не міняючи напрямку погляду.

        Напрямок лишаємо той самий свідомо: людина щойно дивилася на модель
        під зрозумілим їй кутом, і раптова зміна ракурсу збиває з пантелику
        сильніше, ніж допомагає. Але якщо з цього боку місце затулене самим
        тілом, дивитися туди марно — тоді заходимо ззовні, з боку `outward`.
        """
        camera = self.plotter.camera
        eye = np.array(camera.position, dtype=float)
        focus = np.array(camera.focal_point, dtype=float)
        direction = eye - focus
        length = float(np.linalg.norm(direction))
        if length < 1e-12:
            direction = np.array([1.0, -1.0, 0.6])
            length = float(np.linalg.norm(direction))
        direction = direction / length
        if outward is not None:
            out = np.asarray(outward, dtype=float)
            out_len = float(np.linalg.norm(out))
            if out_len > 1e-12:
                out = out / out_len
                if float(np.dot(direction, out)) < 0.25:
                    # Камера дивилася б крізь тіло: заходимо з вулиці,
                    # трохи збоку — так видно і саме місце, і його оточення.
                    direction = out * 0.8 + direction * 0.2
                    direction = direction / float(np.linalg.norm(direction))
        target = np.asarray(point, dtype=float)
        away = max(radius * 6.0, 1e-4)
        camera.focal_point = tuple(target)
        camera.position = tuple(target + direction * away)
        self.plotter.renderer.reset_camera_clipping_range()
        self.plotter.renderer.camera_set = True
        self.plotter.render()

    def show_problem(self, key: str, data, count: int = 0):
        """Шар проблемної геометрії: сама підсвітка плюс стан чекбокса.

        Показати МІСЦЕ важливіше, ніж назвати кількість: «38 дірок» у таблиці
        не каже, чи вони в хвостовому обтічнику, чи рівно там, де ви збираєтесь
        рахувати відрив.
        """
        self._drop(key)
        if data is not None and data.n_points:
            actor = self.plotter.add_mesh(
                data, name=key, reset_camera=False, **_LAYER_STYLE[key])
            self.actors[key] = actor
            # Підсвітка граней лежить рівно на поверхні тіла, тому без зсуву
            # по глибині вони з тілом бʼються за пікселі й підсвітка блимає
            # плямами або зникає зовсім.
            try:
                mapper = actor.GetMapper()
                mapper.SetResolveCoincidentTopologyToPolygonOffset()
                mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(
                    -6, -6)
                mapper.SetRelativeCoincidentTopologyLineOffsetParameters(-6, -6)
            except AttributeError:
                pass
            self.set_visible(key, self.chk[key].isChecked())
        self.set_problem(key, count)
        self.plotter.render()

    def show_holes(self, edges):
        self.show_problem("holes", edges,
                          0 if edges is None else int(edges.n_cells))

    def set_problem(self, key: str, count: int, tip: str = ""):
        """Підпис чекбокса: скільки цього в моделі й що з цим робити."""
        chk = self.chk.get(key)
        if chk is None:
            return
        label, colour, advice = PROBLEM_LAYERS[key]
        if count:
            chk.setEnabled(True)
            chk.setText(tr("{label} {count}", label=label,
                           count=f"{count:,}".replace(",", " ")))
            chk.setStyleSheet(f"color:{colour}; font-weight:bold;")
            chk.setToolTip(advice)
        else:
            chk.setEnabled(False)
            chk.setText(label)
            chk.setStyleSheet("color:#6b7278;")
            chk.setToolTip(tr("{label}: this model does not have it", label=label))

    def mark_spot(self, centre, radius: float):
        """Ставить помітну кулю там, куди щойно підлетіли.

        Саму дірку буває затулено обшивкою — тоді людина дивиться в
        потрібне місце й не бачить нічого. Куля видно завжди, і з неї
        зрозуміло, що камера не промахнулася.
        """
        self._drop("spot")
        if centre is None:
            self.plotter.render()
            return
        sphere = pv.Sphere(radius=max(radius, 1e-5) * 0.75, center=centre)
        self.actors["spot"] = self.plotter.add_mesh(
            sphere, color=COL_SPOT, opacity=0.35, name="spot",
            reset_camera=False)
        self.plotter.render()

    def clear_problems(self):
        self._drop("spot")
        for key in PROBLEM_LAYERS:
            self._drop(key)
            self.set_problem(key, 0)
