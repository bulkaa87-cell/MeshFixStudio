"""The geometry check of a triangle surface, and the data of its problem
layers for the 3D view.

SHARED CODE: this module is the mesh part of fs_geometry.py of OpenFOAM
Studio (reading, units, the check, the problem layers). The CFD parts of
fs_geometry (frontal areas for Cd, the advice for snappyHexMesh, the voxel
wrap, the propeller) stay in OpenFOAM Studio. OpenFOAM Studio adds its
notes to a Diagnosis with NOTE_HOOKS, and asks for the silhouettes with
diagnose(mesh, projected=True).

The check does what `surfaceCheck` of OpenFOAM shows: open edges,
non-manifold edges, degenerate triangles, the number of separate parts,
the orientation of each part, closedness. The fast path is in Rust
(meshfix._native.mesh_check). Without it, the same numbers come from VTK
and numpy.

The inline comments are in Ukrainian: they come from the source module.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pyvista as pv
import vtk

from .i18n import tr

# Functions fn(diagnosis) that add (level, text) notes to a Diagnosis after
# the check. OpenFOAM Studio adds its advice for snappyHexMesh here.
NOTE_HOOKS: list = []


def _rust_mesh():
    """The native module, if it has the check (an old build can lack it)."""
    try:
        from . import _native as rs
    except ImportError:
        return None
    return rs if hasattr(rs, "mesh_check") else None


def _add_notes(d) -> None:
    for fn in NOTE_HOOKS:
        fn(d)


@dataclass
class Diagnosis:
    n_triangles: int = 0
    n_points: int = 0
    open_edges: int = 0
    non_manifold_edges: int = 0
    degenerate: int = 0
    parts: int = 1
    area: float = 0.0
    volume: float = 0.0
    signed_volume: float = 0.0
    bounds: tuple[float, ...] = (0, 0, 0, 0, 0, 0)
    min_edge: float = 0.0
    max_edge: float = 0.0
    median_edge: float = 0.0
    # Медіана НАЙКОРОТШОГО ребра кожного трикутника. Саме вона каже, наскільки
    # дрібно STL описує ФОРМУ, а median_edge — ні.
    #
    # На лофтованому крилі трикутники витягнуті: короткі впоперек хорди, довгі
    # вздовж розмаху. Медіана всіх ребер тоді показує крок між перерізами —
    # величину, що до форми профілю не має стосунку. Вийде «сітка й так
    # дрібніша за трикутники» там, де передня кромка насправді описана з
    # кроком у міліметри.
    short_edge: float = 0.0
    flipped_faces: int = 0      # граней у вивернутих частинах
    inverted_parts: int = 0     # скільки частин вивернуто навиворіт
    bad_winding: int = 0        # ребер, де сусідні трикутники намотані однаково
    # Маска граней вивернутих частин — щоб показати їх у вʼюпорті, не рахуючи
    # все вдруге. Не для друку: це масив на сотні тисяч елементів.
    inverted_cells: object = field(default=None, repr=False)
    projected: tuple[float, float, float] = (0.0, 0.0, 0.0)  # силует по X, Y, Z
    hole_sizes: list[float] = field(default_factory=list)  # діагоналі, спадно
    notes: list[tuple[str, str]] = field(default_factory=list)  # (рівень, текст)

    @property
    def closed(self) -> bool:
        return self.open_edges == 0

    @property
    def largest_hole(self) -> float:
        return self.hole_sizes[0] if self.hole_sizes else 0.0

    @property
    def flipped_fraction(self) -> float:
        return self.flipped_faces / self.n_triangles if self.n_triangles else 0.0

    @property
    def frontal(self) -> float:
        """Міделевий переріз: силует із напрямку потоку (+X)."""
        return self.projected[0]

    @property
    def planform(self) -> float:
        """Площа в плані: силует згори. Для літака це опорна площа крила."""
        return self.projected[2]

    @property
    def streamwise_axis(self) -> int:
        """Вісь, уздовж якої силует найменший — найімовірніший напрямок потоку."""
        if not any(self.projected):
            return 0
        return min(range(3), key=lambda i: self.projected[i])

    @property
    def normals_outward(self) -> bool:
        return self.signed_volume > 0

    @property
    def size(self) -> tuple[float, float, float]:
        b = self.bounds
        return (b[1] - b[0], b[3] - b[2], b[5] - b[4])

    @property
    def diagonal(self) -> float:
        sx, sy, sz = self.size
        return math.sqrt(sx * sx + sy * sy + sz * sz)

    @property
    def worst_level(self) -> str:
        if any(lvl == "bad" for lvl, _ in self.notes):
            return "bad"
        if any(lvl == "warn" for lvl, _ in self.notes):
            return "warn"
        return "ok"



def drop_stray_cells(mesh: pv.PolyData) -> pv.PolyData:
    """Лишає саму поверхню: без окремих точок і ліній.

    `clean` з `polys_to_lines`/`lines_to_points` перетворює вироджені
    трикутники не на ніщо, а на лінії й точки, і вони лишаються в тій самій
    сітці. Для поверхні це сміття, яке ще й збиває лічильники: `n_cells`
    рахує їх усі, а `faces` містить лише многокутники, і будь-яке зіставлення
    «грань -> комірка» після цього розʼїжджається.
    """
    # GetNumberOfPolys, а не n_faces: у pyvista до 0.46 `n_faces` — це
    # застаріла назва для n_cells, і перевірка мовчки нічого б не ловила.
    if int(mesh.n_cells) == int(mesh.GetNumberOfPolys()):
        return mesh
    out = pv.PolyData(mesh.points, mesh.faces)
    # Без явних прапорців clean сам перетворив би вироджені трикутники назад
    # на лінії — те саме сміття, від якого тут і рятуємось.
    return out.clean(point_merging=False, lines_to_points=False,
                     polys_to_lines=False, strips_to_polys=False)



def load_surface(path: str) -> pv.PolyData:
    """Читає STL/OBJ/PLY/VTP і повертає трикутну поверхню.

    Файл без жодного трикутника відкидаємо ТУТ, а не десь далі. Перевірка
    «немає комірок» його не ловить: у хмари точок і в каркаса комірки є, і
    така геометрія доходила до вʼюпорта, де падала на порахунку нормалей —
    уже у вікні, з трасуванням у консоль замість людського повідомлення.
    """
    mesh = pv.read(path)
    if not isinstance(mesh, pv.PolyData):
        mesh = mesh.extract_surface(algorithm="dataset_surface")
    mesh = drop_stray_cells(mesh.triangulate())
    if int(mesh.GetNumberOfPolys()) == 0:
        raise ValueError(
            tr("The file has no triangles: {n_points} points, {n_lines} "
               "lines, {n_verts} separate vertices. This is a point "
               "cloud or a wireframe, not a surface — there is nothing "
               "for the flow to go around here.", n_points=mesh.n_points, n_lines=mesh.n_lines, n_verts=mesh.n_verts))
    return mesh



def guess_scale(mesh: pv.PolyData) -> tuple[float, str]:
    """Здогадка про одиниці. STL безрозмірний, а OpenFOAM працює в метрах.

    Повертає (множник, пояснення). Евристика проста: типова деталь у метрах
    має габарит 0.01..30, у міліметрах — сотні й тисячі.
    """
    b = mesh.bounds
    span = max(b[1] - b[0], b[3] - b[2], b[5] - b[4])
    if span > 300:
        return (0.001, tr("overall size {span:.0f} — most likely millimeters", span=span))
    if span > 30:
        return (0.001, tr("overall size {span:.0f} — maybe millimeters", span=span))
    if span < 0.002:
        return (1000.0, tr("overall size {span:.5g} — maybe kilometers or an error", span=span))
    return (1.0, tr("overall size {span:.4g} — looks like meters", span=span))



def _count_edges(mesh: pv.PolyData, **kw) -> int:
    opts = dict(boundary_edges=False, feature_edges=False,
                manifold_edges=False, non_manifold_edges=False)
    opts.update(kw)
    edges = mesh.extract_feature_edges(**opts)
    return int(edges.n_cells)



def _tri_faces(mesh: pv.PolyData) -> np.ndarray | None:
    """Трикутники як (N, 3) або None, якщо поверхня не трикутна."""
    faces = mesh.faces
    if faces.size == 0 or faces.size % 4:
        return None
    faces = faces.reshape(-1, 4)
    if not np.all(faces[:, 0] == 3):
        return None
    return faces[:, 1:]



def _count_regions(mesh: pv.PolyData) -> int:
    conn = vtk.vtkPolyDataConnectivityFilter()
    conn.SetInputData(mesh)
    conn.SetExtractionModeToAllRegions()
    conn.Update()
    return int(conn.GetNumberOfExtractedRegions())



_CELL_TAG = "_fs_cell"



def _region_ids(mesh: pv.PolyData) -> tuple[int, np.ndarray]:
    """(скільки незвʼязаних частин, номер частини для кожної грані).

    ПАСТКА, на якій легко втратити день: vtkPolyDataConnectivityFilter віддає
    точки й грані В ІНШОМУ ПОРЯДКУ, ніж отримав. Читати його RegionId по
    індексах вхідної сітки не можна — номери лягають не на ті грані. На
    реальній моделі це давало 22 633 трикутники, чиї три вершини нібито
    належать різним частинам, і «ремонт нормалей» вивертав половину деталі.

    Тому кожній грані ще до фільтра чіпляємо її власний номер (cell_data
    фільтр переносить чесно) і вертаємо результат у вхідний порядок.
    """
    rs = _rust_mesh()
    arrays = _pure_triangles(mesh) if rs is not None else None
    if arrays is not None:
        # Rust: ті самі частини (грані зі спільною вершиною) і та сама
        # нумерація — за першою гранню, як у VTK; уже у вхідному порядку.
        r = rs.mesh_check(*arrays)
        return int(r["n_regions"]), np.asarray(r["regions"], dtype=np.int64)
    zero = np.zeros(int(mesh.n_cells), dtype=np.int64)
    if int(mesh.GetNumberOfPolys()) != int(mesh.n_cells):
        # У сітці є ще й точкові або лінійні комірки: нумерація граней і
        # комірок розходиться, зіставляти їх навмання не можна.
        return _count_regions(mesh), zero
    probe = pv.PolyData(mesh.points, mesh.faces)
    probe.cell_data[_CELL_TAG] = np.arange(probe.n_cells, dtype=np.int64)

    conn = vtk.vtkPolyDataConnectivityFilter()
    conn.SetInputData(probe)
    conn.SetExtractionModeToAllRegions()
    conn.SetColorRegions(True)
    conn.Update()
    n = int(conn.GetNumberOfExtractedRegions())

    out = pv.wrap(conn.GetOutput())
    faces_out = _tri_faces(out)
    if (faces_out is None or "RegionId" not in out.point_data
            or _CELL_TAG not in out.cell_data):
        return n, zero
    ids = np.asarray(out.point_data["RegionId"])
    orig = np.asarray(out.cell_data[_CELL_TAG])
    if orig.size != mesh.n_cells or ids.size != out.n_points:
        return n, zero
    regions = zero.copy()
    regions[orig] = ids[faces_out[:, 0]]
    return n, regions



def _part_volumes(mesh: pv.PolyData, regions: np.ndarray,
                  n_regions: int) -> np.ndarray:
    """Знаковий обʼєм кожної частини. Мінус — частина вивернута навиворіт."""
    faces = _tri_faces(mesh)
    if faces is None or n_regions == 0:
        return np.zeros(max(n_regions, 0))
    p = mesh.points
    v0, v1, v2 = p[faces[:, 0]], p[faces[:, 1]], p[faces[:, 2]]
    vol = np.einsum("ij,ij->i", v0, np.cross(v1, v2)) / 6.0
    return np.bincount(regions, weights=vol, minlength=n_regions)



def inverted_mask(mesh: pv.PolyData, regions: np.ndarray | None = None,
                  n_regions: int = 0) -> np.ndarray:
    """Маска граней, що належать вивернутим навиворіт частинам.

    Саме ця перевірка, а не узгодженість намотки, ловить типову ваду збірки
    з CAD: кожна деталь усередині себе намотана бездоганно, але частина з них
    дивиться нормалями всередину. У Blender цього не видно — його вʼюпорт
    світить із двох боків, тому вивернута деталь виглядає нормальною.
    """
    if regions is None:
        n_regions, regions = _region_ids(mesh)
    vols = _part_volumes(mesh, regions, n_regions)
    bad = np.where(vols < 0)[0]
    if bad.size == 0:
        return np.zeros(int(mesh.n_cells), dtype=bool)
    return np.isin(regions, bad)



def inverted_part_count(mesh: pv.PolyData) -> tuple[int, int]:
    """(скільки частин вивернуто, скільки в них граней).

    Те саме, що робить повна діагностика, але без решти її роботи: для
    позначки біля моделі в списку потрібні лише ці два числа.
    """
    n_regions, regions = _region_ids(mesh)
    vols = _part_volumes(mesh, regions, n_regions)
    bad = np.where(vols < 0)[0]
    if bad.size == 0:
        return (0, 0)
    return (int(bad.size), int(np.count_nonzero(np.isin(regions, bad))))



def _bad_winding_edges(mesh: pv.PolyData) -> int:
    """Ребра, де два сусідні трикутники обходяться в ОДИН бік.

    Це і є справжня неузгодженість намотки: у нормально зшитій поверхні
    спільне ребро двох трикутників кожен із них проходить у свій бік. Рахуємо
    з самої топології, а не з vtkPolyDataNormals: той на збірці з
    non-manifold ребрами вигадує вивернуті ділянки там, де їх немає.
    """
    faces = _tri_faces(mesh)
    if faces is None:
        return 0
    n = int(mesh.n_points)
    e = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    directed = e[:, 0].astype(np.int64) * n + e[:, 1]
    und = np.sort(e, axis=1)
    key = und[:, 0].astype(np.int64) * n + und[:, 1]

    order = np.argsort(key, kind="stable")
    key_s, dir_s = key[order], directed[order]
    uniq, start, count = np.unique(key_s, return_index=True, return_counts=True)
    two = start[count == 2]
    if two.size == 0:
        return 0
    return int(np.count_nonzero(dir_s[two] == dir_s[two + 1]))



def _signed_volume(mesh: pv.PolyData) -> float:
    """Обʼєм через теорему про дивергенцію: V = 1/6 * sum(v0 . (v1 x v2)).

    Знак каже, чи нормалі дивляться назовні. Для незамкненої поверхні число
    не має фізичного сенсу, але знак усе одно корисний.
    """
    faces = mesh.faces.reshape(-1, 4)
    if faces.size == 0 or not np.all(faces[:, 0] == 3):
        return 0.0
    p = mesh.points
    v0, v1, v2 = p[faces[:, 1]], p[faces[:, 2]], p[faces[:, 3]]
    return float(np.sum(np.einsum("ij,ij->i", v0, np.cross(v1, v2))) / 6.0)



def _hole_sizes(mesh: pv.PolyData, limit: int = 400) -> list[float]:
    """Розмір кожної дірки — діагональ габариту її контуру, за спаданням.

    Саме це число вирішує долю сітки: дірку, дрібнішу за комірку в тій зоні,
    snappyHexMesh затягує сам (усі комірки навколо неї він однаково зрізає),
    а більша стає наскрізним каналом усередину тіла.
    """
    edges = mesh.extract_feature_edges(
        boundary_edges=True, feature_edges=False,
        manifold_edges=False, non_manifold_edges=False)
    if edges.n_cells == 0:
        return []

    conn = vtk.vtkPolyDataConnectivityFilter()
    conn.SetInputData(edges)
    conn.SetExtractionModeToAllRegions()
    conn.SetColorRegions(True)
    conn.Update()
    labelled = pv.wrap(conn.GetOutput())
    if "RegionId" not in labelled.point_data:
        return []

    ids = np.asarray(labelled.point_data["RegionId"])
    pts = labelled.points
    sizes = []
    for region in range(min(conn.GetNumberOfExtractedRegions(), limit)):
        p = pts[ids == region]
        if len(p) < 2:
            continue
        sizes.append(float(np.linalg.norm(p.max(axis=0) - p.min(axis=0))))
    sizes.sort(reverse=True)
    return sizes



def projected_areas(mesh: pv.PolyData,
                    target_voxels: int = 6_000_000) -> tuple[float, float, float]:
    """Площі силуету тіла вздовж X, Y, Z — рахуємо растром, а не формулою.

    ЧОМУ НЕ ФОРМУЛОЮ. Раніше тут стояла половина суми |n_i| * area по всіх
    гранях. Це точно лише для ВИПУКЛОГО тіла, де кожен промінь перетинає
    поверхню двічі. Літак невипуклий: промінь уздовж X проходить і крізь
    фюзеляж, і крізь корінь крила — чотири перетини, і формула лічить два
    силуети замість одного. Виміряно на хресті з двох циліндрів, де відповідь
    відома точно (0.04 м²): формула дає 0.0478 (+20%), растр — 0.0398
    (-0.6%). На реальній збірці з внутрішніми стінками формула завищувала
    мідель удвічі.

    Ціна помилки пряма: Aref входить у знаменник Cd і Cl.

    РАСТРОМ. Воксельна оболонка тіла, спроєктована на кожну площину. Растр
    «товщає» на пів вокселя по контуру, тому віднімаємо половину межової
    смуги — на аналітичних тілах це дає похибку в межах 1%.
    """
    if mesh.n_cells == 0 or int(mesh.GetNumberOfPolys()) == 0:
        return (0.0, 0.0, 0.0)
    b = np.array(mesh.bounds).reshape(3, 2)
    size = b[:, 1] - b[:, 0]
    span = float(size.max())
    if span <= 0:
        return (0.0, 0.0, 0.0)

    # Плоске тіло має нульовий габарит по одній осі — для вибору вокселя
    # підставляємо туди тонкий, але не нульовий розмір.
    thick = np.maximum(size, span / 1000.0)
    voxel = float((float(np.prod(thick)) / target_voxels) ** (1.0 / 3.0))
    # Не грубіше за 1/40 найбільшої сторони (інакше контур силуету з
    # кількох пікселів) і не дрібніше за 1/600 (інакше сітка не влізе).
    voxel = min(max(voxel, span / 600.0), span / 40.0)

    origin, dims = _voxel_grid(mesh, voxel, pad=2)
    rs = _rust_mesh()
    arrays = _pure_triangles(mesh) if rs is not None else None
    if arrays is not None:
        # Той самий растр, що й vtkVoxelModeller (точка сітки на оболонці,
        # якщо до трикутника ≤ max_dist), але одразу три проєкції.
        span_grid = max((d - 1) * voxel for d in dims)
        max_dist = min(1.0, voxel / span_grid) * span_grid if span_grid > 0 else voxel
        flats = [np.asarray(f) > 0 for f in rs.shell_projections(
            arrays[0], arrays[1], tuple(float(v) for v in origin),
            tuple(int(v) for v in dims), float(voxel), float(max_dist))]
    else:
        shell = _shell_voxels(mesh, origin, dims, voxel)
        flats = [shell.any(axis=axis) for axis in range(3)]
    out = []
    for axis in range(3):
        flat = flats[axis]
        if not flat.any():
            out.append(0.0)
            continue
        inner = flat.copy()
        for plane_axis in range(2):
            for shift in (1, -1):
                inner &= np.roll(flat, shift, axis=plane_axis)
        border = float(flat.sum() - inner.sum())
        out.append(max(0.0, (float(flat.sum()) - 0.5 * border)) * voxel * voxel)
    return (out[0], out[1], out[2])



def open_edges_polydata(mesh: pv.PolyData) -> pv.PolyData:
    """Самі відкриті ребра — щоб підсвітити їх у вʼюпорті.

    Показати місце проблеми важливіше, ніж назвати її кількість: дірки в
    імпортованій моделі майже завжди сидять у кількох конкретних вузлах
    (пази, стики деталей, зрізи), і побачивши їх, зрозуміло, що правити.
    """
    return mesh.extract_feature_edges(
        boundary_edges=True, feature_edges=False,
        manifold_edges=False, non_manifold_edges=False)



def hole_report(mesh: pv.PolyData, limit: int = 12) -> list[tuple[float, tuple]]:
    """[(розмір, центр)] для найбільших дірок, за спаданням розміру."""
    edges = open_edges_polydata(mesh)
    if edges.n_cells == 0:
        return []

    conn = vtk.vtkPolyDataConnectivityFilter()
    conn.SetInputData(edges)
    conn.SetExtractionModeToAllRegions()
    conn.SetColorRegions(True)
    conn.Update()
    labelled = pv.wrap(conn.GetOutput())
    if "RegionId" not in labelled.point_data:
        return []

    ids = np.asarray(labelled.point_data["RegionId"])
    pts = labelled.points
    out = []
    for region in range(conn.GetNumberOfExtractedRegions()):
        p = pts[ids == region]
        if len(p) < 2:
            continue
        size = float(np.linalg.norm(p.max(axis=0) - p.min(axis=0)))
        out.append((size, tuple(float(v) for v in p.mean(axis=0))))
    out.sort(key=lambda t: -t[0])
    return out[:limit]



def problem_spots(mesh: pv.PolyData, diagnosis, limit: int = 10) -> list[dict]:
    """Де саме сидять проблеми: [{вид, розмір, центр}], найбільші спершу.

    Підсвітка показує проблеми на моделі, але знайти рожеву цятку в 775
    тисячах трикутників очима — окрема робота. Це список, яким можна
    ходити камерою.
    """
    spots: list[dict] = []
    for size, centre in hole_report(mesh, limit=limit):
        spots.append({"kind": "holes", "size": size, "centre": centre,
                      "what": "hole"})

    mask = getattr(diagnosis, "inverted_cells", None)
    if mask is not None:
        inverted = inverted_polydata(mesh, mask)
        if inverted is not None and inverted.n_cells:
            conn = vtk.vtkPolyDataConnectivityFilter()
            conn.SetInputData(inverted)
            conn.SetExtractionModeToAllRegions()
            conn.SetColorRegions(True)
            conn.Update()
            labelled = pv.wrap(conn.GetOutput())
            ids = np.asarray(labelled.point_data.get("RegionId", []))
            pts = labelled.points
            groups = []
            for region in range(min(conn.GetNumberOfExtractedRegions(), 200)):
                pick = pts[ids == region] if ids.size else pts
                if len(pick) < 3:
                    continue
                span = float(np.linalg.norm(pick.max(axis=0) - pick.min(axis=0)))
                groups.append((span, tuple(float(v) for v in pick.mean(axis=0))))
            groups.sort(key=lambda g: -g[0])
            for span, centre in groups[:limit]:
                spots.append({"kind": "flip", "size": span, "centre": centre,
                              "what": "flipped part"})

    degen = degenerate_points(mesh)
    if degen is not None and degen.n_points:
        step = max(1, degen.n_points // limit)
        for point in np.asarray(degen.points)[::step][:limit]:
            spots.append({"kind": "degen", "size": 0.0,
                          "centre": tuple(float(v) for v in point),
                          "what": "degenerate triangle"})

    spots.sort(key=lambda spot: -spot["size"])
    return spots



def _edge_stats(mesh: pv.PolyData) -> tuple[float, float, float, float]:
    """(найкоротше, найдовше, медіана всіх, медіана найкоротших у трикутнику).

    Останнє окремо, бо трикутники бувають витягнуті. У лофтованого крила
    кожен трикутник має одне коротке ребро впоперек хорди й два довгих
    уздовж розмаху: медіана всіх ребер тоді описує крок між перерізами, а
    медіана коротких — те, наскільки дрібно передано сам профіль.
    """
    faces = mesh.faces.reshape(-1, 4)
    if faces.size == 0:
        return (0.0, 0.0, 0.0, 0.0)
    p = mesh.points
    a, b, c = p[faces[:, 1]], p[faces[:, 2]], p[faces[:, 3]]
    sides = np.column_stack([
        np.linalg.norm(b - a, axis=1),
        np.linalg.norm(c - b, axis=1),
        np.linalg.norm(a - c, axis=1),
    ])
    lens = sides.reshape(-1)
    lens = lens[lens > 0]
    if lens.size == 0:
        return (0.0, 0.0, 0.0, 0.0)
    shortest = sides.min(axis=1)
    shortest = shortest[shortest > 0]
    short = float(np.median(shortest)) if shortest.size else float(lens.min())
    return (float(lens.min()), float(lens.max()), float(np.median(lens)),
            short)



def _pure_triangles(mesh: pv.PolyData):
    """(points float64 (N,3), tris int64 (M,3)), якщо сітка — самі
    трикутники; інакше None (тоді лишається шлях VTK/numpy)."""
    if mesh.n_cells == 0 or int(mesh.GetNumberOfPolys()) != int(mesh.n_cells):
        return None
    faces = _tri_faces(mesh)
    if faces is None or faces.shape[0] != mesh.n_cells:
        return None
    return (np.ascontiguousarray(mesh.points, dtype=np.float64),
            np.ascontiguousarray(faces, dtype=np.int64))



def diagnose(mesh: pv.PolyData, projected: bool = False) -> Diagnosis:
    """Повна перевірка геометрії.

    projected=True also computes the silhouettes along X, Y and Z
    (Diagnosis.projected, for the frontal area of a CFD case). It is slow
    on a large mesh, thus it is off by default.

    На Rust (foamrs.mesh_check), якщо він є: ті самі числа за один прохід
    (250 тис. трикутників — десятки мілісекунд замість ~1.4 с, а
    відкриття проєкту перевіряло сцену кілька разів поспіль).
    """
    rs = _rust_mesh()
    arrays = _pure_triangles(mesh) if rs is not None else None
    if arrays is not None:
        return _diagnose_rust(mesh, rs, *arrays, projected=projected)
    d = Diagnosis()
    d.n_triangles = int(mesh.n_cells)
    d.n_points = int(mesh.n_points)
    d.bounds = tuple(float(x) for x in mesh.bounds)

    d.open_edges = _count_edges(mesh, boundary_edges=True)
    d.non_manifold_edges = _count_edges(mesh, non_manifold_edges=True)
    n_regions, regions = _region_ids(mesh)
    d.parts = n_regions

    sized = mesh.compute_cell_sizes(length=False, area=True, volume=False)
    areas = np.asarray(sized.cell_data["Area"])
    d.area = float(areas.sum())
    # Поріг вироджености: площа менша за 1e-10 від середньої.
    if areas.size:
        d.degenerate = int(np.count_nonzero(areas < max(areas.mean() * 1e-10, 1e-24)))


    vols = _part_volumes(mesh, regions, n_regions)
    bad = np.where(vols < 0)[0]
    d.inverted_parts = int(bad.size)
    d.inverted_cells = np.isin(regions, bad) if bad.size else None
    d.flipped_faces = int(d.inverted_cells.sum()) if bad.size else 0
    d.bad_winding = _bad_winding_edges(mesh)
    if projected:
        d.projected = projected_areas(mesh)
    d.signed_volume = _signed_volume(mesh)
    d.volume = abs(d.signed_volume)
    d.min_edge, d.max_edge, d.median_edge, d.short_edge = _edge_stats(mesh)
    if d.open_edges:
        d.hole_sizes = _hole_sizes(mesh)

    _add_notes(d)
    return d



def _diagnose_rust(mesh, rs, pts, tris, projected: bool = False) -> Diagnosis:
    d = Diagnosis()
    d.n_triangles = int(mesh.n_cells)
    d.n_points = int(mesh.n_points)
    d.bounds = tuple(float(x) for x in mesh.bounds)
    r = rs.mesh_check(pts, tris)
    d.open_edges = int(r["open_edges"])
    d.non_manifold_edges = int(r["non_manifold_edges"])
    d.parts = int(r["n_regions"])
    regions = np.asarray(r["regions"])
    d.area = float(r["area"])
    d.degenerate = int(r["degenerate"])
    vols = np.asarray(r["part_volumes"])
    bad = np.where(vols < 0)[0]
    d.inverted_parts = int(bad.size)
    d.inverted_cells = np.isin(regions, bad) if bad.size else None
    d.flipped_faces = int(d.inverted_cells.sum()) if bad.size else 0
    d.bad_winding = int(r["bad_winding"])
    if projected:
        d.projected = projected_areas(mesh)
    d.signed_volume = float(r["signed_volume"])
    d.volume = abs(d.signed_volume)
    d.min_edge, d.max_edge, d.median_edge, d.short_edge = (
        float(x) for x in r["edge_stats"])
    if d.open_edges:
        d.hole_sizes = [float(x) for x in r["hole_sizes"]]
    _add_notes(d)
    return d



def apply_scale(mesh: pv.PolyData, factor: float) -> pv.PolyData:
    if factor == 1.0:
        return mesh
    out = mesh.copy()
    out.points = out.points * factor
    return out



def display_mesh(mesh: pv.PolyData, feature_angle: float = 45.0) -> pv.PolyData:
    """Копія поверхні з нормалями, придатними для показу на екрані.

    Робить рівно те, чого НЕ можна довіряти типовому `smooth_shading=True`:
    той щоразу перераховує нормалі з `non_manifold_traversal=True` і на
    брудній збірці вивертає кожну сьому грань — вони темніють, і модель
    виглядає рваною, хоч у файлі все гаразд.

    `split_vertices` лишає різкими справжні кромки: без нього нормалі
    усереднюються через гравіювання панелей, і поверхня пливе.
    """
    if int(mesh.GetNumberOfPolys()) == 0:
        # Нема з чого рахувати нормалі: віддаємо як є, щоб вʼюпорт показав
        # хоч що-небудь, а не впав із трасуванням.
        return mesh.copy()
    out = orient_parts_outward(mesh)
    out.compute_normals(cell_normals=True, point_normals=True,
                        consistent_normals=False, auto_orient_normals=False,
                        non_manifold_traversal=False,
                        split_vertices=True, feature_angle=feature_angle,
                        inplace=True)
    return out



def non_manifold_polydata(mesh: pv.PolyData) -> pv.PolyData:
    """Non-manifold ребра — щоб показати, де саме деталі врізані одна в одну."""
    return mesh.extract_feature_edges(
        boundary_edges=False, feature_edges=False,
        manifold_edges=False, non_manifold_edges=True)



def inverted_polydata(mesh: pv.PolyData,
                      mask: np.ndarray | None = None) -> pv.PolyData | None:
    """Грані вивернутих частин окремою поверхнею — для підсвітки."""
    if mask is None:
        mask = inverted_mask(mesh)
    mask = np.asarray(mask, dtype=bool)
    if mask.size != mesh.n_cells or not mask.any():
        return None
    return mesh.extract_cells(np.where(mask)[0]).extract_surface(
        algorithm="dataset_surface")



def degenerate_points(mesh: pv.PolyData) -> pv.PolyData | None:
    """Центри вироджених трикутників. Самих трикутників не видно — площа нуль,
    тому показуємо точки: інакше «6 вироджених» у таблиці ні про що не каже."""
    faces = _tri_faces(mesh)
    if faces is None:
        return None
    p = mesh.points
    v0, v1, v2 = p[faces[:, 0]], p[faces[:, 1]], p[faces[:, 2]]
    area = np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1) / 2.0
    if not area.size:
        return None
    bad = area < max(area.mean() * 1e-10, 1e-24)
    if not bad.any():
        return None
    centres = (v0[bad] + v1[bad] + v2[bad]) / 3.0
    return pv.PolyData(centres)



def orient_parts_outward(mesh: pv.PolyData) -> pv.PolyData:
    """Розвертає назовні КОЖНУ незвʼязану частину окремо.

    Глобального знака обʼєму для збірки не досить: у моделі з 24 деталей
    17 можуть дивитися всередину, а сумарний обʼєм лишатиметься додатним.
    vtkPolyDataNormals з auto_orient_normals теж не рятує — він вимагає
    замкненої manifold-поверхні, а тут її немає.
    """
    faces = _tri_faces(mesh)
    if faces is None:
        return mesh.copy()
    mask = inverted_mask(mesh)
    if not mask.any():
        return mesh.copy()
    flipped = faces.copy()
    flipped[mask] = flipped[mask][:, [0, 2, 1]]
    out = mesh.copy()
    out.faces = np.hstack(
        [np.full((len(flipped), 1), 3, dtype=flipped.dtype), flipped]).ravel()
    # Масиви нормалей після перевертання намотки застаріли: лишити їх —
    # означає отримати поверхню, де нормаль і обхід дивляться в різні боки,
    # а це саме те, від чого тут рятуємось.
    out.cell_data.pop("Normals", None)
    out.point_data.pop("Normals", None)
    return out



def _voxel_grid(mesh: pv.PolyData, voxel: float,
                pad: int = 4) -> tuple[np.ndarray, tuple[int, int, int]]:
    """Початок і розміри сітки вокселів. Запас по краях — щоб тіло не
    торкалося межі: заливка ззовні мусить мати звідки початися."""
    b = np.array(mesh.bounds).reshape(3, 2)
    size = b[:, 1] - b[:, 0]
    margin = voxel * pad
    dims = np.ceil((size + 2 * margin) / voxel).astype(int) + 1
    return b[:, 0] - margin, tuple(int(v) for v in dims)



def _blank(origin, dims, voxel: float, fill: int = 0) -> vtk.vtkImageData:
    img = vtk.vtkImageData()
    img.SetDimensions(*dims)
    img.SetSpacing(voxel, voxel, voxel)
    img.SetOrigin(*[float(v) for v in origin])
    img.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
    img.GetPointData().GetScalars().Fill(fill)
    return img



def _as_mask(img, dims) -> np.ndarray:
    return np.asarray(pv.wrap(img).point_data.active_scalars).reshape(
        dims, order="F") > 0



def _shell_voxels(mesh, origin, dims, voxel) -> np.ndarray:
    """Воксели, крізь які проходить сама поверхня. Орієнтації не потребує.

    `SetMaximumDistance` у VTK — НЕ відстань, а ЧАСТКА габариту моделі,
    обрізана до 1. Тут довго стояв сам воксель у метрах, і це працювало
    випадково: на моделі в пів метра частка виходила близько вокселя. Але
    модель у 514 «метрів» (міліметровий файл при вибраних метрах) давала
    1.96 → 1.0, тобто кожен із 227 тис. трикутників обходив усі 6.6 млн
    вокселів — програма «висла» на годину. А на дрібних тілах навпаки:
    зона пошуку 0.2 вокселя губила оболонку, хрест циліндрів 10 см мав
    силует на 2.5% менший.

    Сам растр від цього параметра не залежить, щойно зона ≥ одного вокселя:
    позначаються ті самі воксели (перевірено — 1, 1.5 і 2 вокселі дають
    той самий масив). Тому ставимо рівно один воксель як частку габариту:
    силует кулі +0.33% і хреста −0.1% на будь-якому масштабі, 0.1–0.3 с.
    """
    model = vtk.vtkVoxelModeller()
    model.SetInputData(mesh)
    model.SetSampleDimensions(*dims)
    model.SetModelBounds(
        float(origin[0]), float(origin[0] + (dims[0] - 1) * voxel),
        float(origin[1]), float(origin[1] + (dims[1] - 1) * voxel),
        float(origin[2]), float(origin[2] + (dims[2] - 1) * voxel))
    model.SetScalarTypeToUnsignedChar()
    model.SetForegroundValue(1)
    model.SetBackgroundValue(0)
    span = max((d - 1) * voxel for d in dims)
    model.SetMaximumDistance(min(1.0, voxel / span) if span > 0 else 1.0)
    model.Update()
    return _as_mask(model.GetOutput(), dims)



def write_stl(mesh: pv.PolyData, path: str, binary: bool = True) -> None:
    """Пише STL для constant/triSurface. Геометрія вже має бути в метрах."""
    mesh.save(path, binary=binary)



def problem_layers(mesh, d) -> dict:
    """The data of the problem layers of the 3D view, without a widget.

    It was MainWindow._problem_layers of OpenFOAM Studio. On a large mesh
    this takes seconds: call it in the worker thread, show it in the window.
    """
    return {
        "holes": (open_edges_polydata(mesh) if d.open_edges else None),
        "flip": (inverted_polydata(mesh, d.inverted_cells)
                 if d.flipped_faces else None),
        "nm": (non_manifold_polydata(mesh) if d.non_manifold_edges else None),
        "degen": (degenerate_points(mesh) if d.degenerate else None),
    }
