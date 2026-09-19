# plateau-lod2-mlt-pipeline 設計書

PLATEAU の CityGML（建築物 LOD2）から MapLibre Tile（MLT）と PMTiles を生成するパイプラインの設計書。
[indigo-lab/plateau-lod2-mvt](https://github.com/indigo-lab/plateau-lod2-mvt)（2020 年度・東京 23 区・MVT ディレクトリ配信）を、
現行の PLATEAU データ（標準製品仕様書 4.1 / 5 系）と現行のタイル形式（MLT、PMTiles）で再構成する。

- 作成日: 2026-09-19
- 状態: 実装済み（変換スクリプト、ビルドスクリプト、ビューア）。千代田区 2025 でのビルドまで確認済み（8 章）

---

## 1. 目的とスコープ

### 1.1 目的

- PLATEAU CityGML の `bldg:Building` のうち LOD2 が整備された建物は屋根面（`bldg:RoofSurface`）単位、それ以外は LOD0 屋根伏せ（`bldg:lod0RoofEdge`）単位のポリゴンに変換し、高さ属性を付与したベクトルタイルを作る。
- タイルは MVT ではなく MLT（MapLibre Tile v1）を主形式とし、PMTiles コンテナで配信する。MVT 版の PMTiles も併せて出力し、比較・互換用途に使う。`{z}/{x}/{y}.mlt` ディレクトリ出力はオプション（`--dir`）に留める（8.4 節）。
- MapLibre GL JS の `fill-extrusion` で indigo-lab 版と同等以上の「積み木調」3D 表示ができることを確認する。

### 1.2 成果物

| 区分 | 成果物 | 備考 |
| --- | --- | --- |
| 変換 | `scripts/citygml2geojson.py` | CityGML → GeoJSON（NDJSON）変換スクリプト（Python + lxml） |
| ビルド | `scripts/build_tiles.sh` | tippecanoe → PMTiles(MVT) → mlt convert → PMTiles(MLT) を一括実行（WSL / Linux / macOS）。`--dir` で MLT ディレクトリと TileJSON も出力 |
| タイル | `dist/<name>.mvt.pmtiles` | MVT を格納した PMTiles（tippecanoe 直接出力） |
| タイル | `dist/<name>.mlt.pmtiles` | MLT を格納した PMTiles（tile_type = 0x06） |
| ビューア | `index.html` | MapLibre GL JS + pmtiles.js のデモ（MLT / MVT の PMTiles を切替） |
| 文書 | `README.md`, `docs/design.md` | 利用者向け説明と本設計書 |

### 1.3 スコープ外

- 壁面（`bldg:WallSurface`）や LOD3 以上の表現。2D ポリゴンへ落とすと線に潰れるため対象外。
- テクスチャ（`*_appearance` ディレクトリ）。
- 建築物以外の地物（tran、veg、frn など）。

---

## 2. 入力データの調査結果

### 2.1 対象データセット

| 項目 | 千代田区 2025 年度 |
| --- | --- |
| データセット | `13101_chiyoda-ku_pref_2025_citygml_1_op` |
| 配布元 | [G 空間情報センター](https://www.geospatial.jp/ckan/dataset/plateau-13101-chiyoda-ku-2025) |
| 準拠仕様 | 3D 都市モデル標準製品仕様書 第 5 版 |
| CityGML / i-UR | CityGML 2.0 / uro 3.2 |
| 座標参照系 | EPSG:6697（JGD2011 緯度経度 + 標高） |
| 建築物 LOD（README 記載） | LOD1 全域（12,576 棟）、LOD2.0 5,341 棟 / LOD2.2 4,447 棟。LOD3.0 も少数あり |
| bldg ファイル | 21 メッシュ（3 次メッシュ単位）、2.03 GB。テクスチャは別ディレクトリ |
| ファイル内の建物の所属 | メッシュが区境をまたぐため、隣接区（中央・港・新宿・文京・台東）の建物も同じファイルに入っている。`uro:city`（＝ `uro:buildingID` の先頭 5 桁）で区別できる |
| CityGML zip | 2,107,396,115 bytes（2026-03-16 版）。ダウンロード・展開済み |
| ローカル配置 | `Documents/GIS/mlit/3D都市モデル（Project PLATEAU）/千代田区/udx/bldg/`（zip にトップディレクトリが無いため直下に展開） |

他の自治体・年度のデータ（uro 3.1 など）も同じスクリプトで処理できることを要件とし、名前空間 URI の版差はワイルドカードで吸収する。

### 2.2 実測値

`udx/bldg/*.gml` 21 ファイルを全走査した結果。ファイルには隣接区の建物も含まれるため、「ファイル全体」と「千代田区（`uro:city = 13101`）のみ」を分けて示す。README の棟数（LOD1 12,576 棟、LOD2.0 5,341 棟、LOD2.2 4,447 棟）は千代田区のみの値と一致する。

| 項目 | ファイル全体 | 千代田区のみ | 設計への影響 |
| --- | --- | --- | --- |
| `bldg:Building` 総数 | 38,743 | 12,558 | 変換対象は `--city 13101` で千代田区に絞る（3.6 節） |
| LOD2 建物（`bldg:lod2Solid` あり） | 27,916（72.1%） | 9,788（77.9%。LOD2.0 5,341 / LOD2.2 4,447） | 残り 2,770 棟は LOD0 屋根伏せへフォールバックする |
| `uro:lodType` 内訳 | 2.0: 17,747 / 2.2: 10,169 / 3.0: 21 | 2.0: 5,341 / 2.2: 4,447 | LOD3.0 建物（`bldg:lod3Solid` 21 件）は港区分に含まれる |
| 屋根面ポリゴン（`RoofSurface/lod2MultiSurface`） | 180,572 | 71,367 | 出力フィーチャ数の目安（LOD2 分） |
| 面積 0.1 m² 未満の屋根面 | 3,217 | 1,425（2.0%） | 既定で除外 |
| `measuredHeight = -9999` | 1,041 | 499（4.0%） | lod1Solid の高さで代替 |
| 1 棟あたりの屋根面数（千代田区） | | 中央値 5、95 パーセンタイル 22、最大 290 | 面単位の高さを持たせる根拠 |

以下はファイル全体での確認結果（構造の確認が目的なので区で絞っていない）。

| 項目 | 値 | 設計への影響 |
| --- | --- | --- |
| `bldg:RoofSurface` 数 | 179,418 | |
| `bldg:GroundSurface` 数 | 28,426（LOD2 建物すべてに 1 つ以上） | 地盤高は GroundSurface から取れる。無い場合の予備ロジックは念のため実装 |
| `bldg:OuterFloorSurface` / `OuterCeilingSurface` | 503 / 457 | 上向き面である OuterFloorSurface は屋根面と同等に扱えるが、既定では含めない（オプション） |
| `bldg:WallSurface` | 350,265 | 対象外 |
| `bldg:BuildingPart` | 0 | 実装は `bldg:Building` 配下を再帰的に走査して BuildingPart があっても拾う |
| `bldg:lod0RoofEdge` | 38,743（全棟、z はすべて 0） | LOD0 フォールバックの形状ソース。`lod0FootPrint` は 0 件だが実装は両対応 |
| `bldg:lod1Solid` | 38,743（全棟） | LOD1 の高さ（z 最大 − 最小）の算出に使える。中央値 12.5 m、最大 251.7 m |
| `bldg:measuredHeight` | 全棟にあるが 1,041 棟が `-9999`（`uro:lod1HeightType = 0` 取得不可） | measuredHeight を無条件に使えない。負値は欠損扱いにする |
| lod1Solid 高さ − measuredHeight | 中央値 −1.6 m、p1 −14.4 m、p99 +0.9 m | measuredHeight は最高高さ、lod1Solid は点群中央値（`lod1HeightType = 2`）由来で系統的に異なる |
| 屋根面 1 枚あたりの 2D 面積 < 0.1 m² | 3,217 枚（1.8%） | 急勾配・ほぼ鉛直な面。既定で除外（閾値はオプション） |
| 内周（穴）を持つ屋根面 | 584 枚 | GeoJSON の内周リングとして保持する。必須 |
| 建物平均高さが measuredHeight より 20 m 以上低い建物 | 283 棟 | 3.3 節の根拠 |
| `srsName` の位置 | `gml:Envelope` のみ。`gml:MultiSurface` には付かない（610,094 件すべて None） | ジオメトリ要素の `srsName` に依存せず、EPSG:6697（緯度経度順）を既定とする |
| LOD3 建物の面の持ち方 | 同じ `bldg:Building` の中に、`lod2MultiSurface` を持つ面と `lod3MultiSurface` を持つ面が別々の `boundedBy` として並ぶ（例: RoofSurface 15 面のうち LOD2 9 面、LOD3 6 面。両方を持つ面は 0） | 屋根面は `bldg:lod2MultiSurface` 配下のポリゴンだけを読む。`lod3MultiSurface` を読むと LOD2 と二重になる |
| `gml:pos`（posList 以外）の使用 | 0 | 実装は両対応 |
| `gml:id` の重複（ファイル間） | 0 | メッシュ境界での二重登録なし |
| 座標順 | 緯度 経度 標高（EPSG:6697） | GeoJSON 化時に経度・緯度へ入れ替え |

### 2.3 CityGML の要素構造（変換に使う部分）

```text
core:CityModel
└ core:cityObjectMember
  └ bldg:Building @gml:id
    ├ bldg:measuredHeight @uom="m"                 … 最高高さ。-9999 は欠損
    ├ bldg:lod0RoofEdge/gml:MultiSurface/…/gml:Polygon   … 屋根伏せ（z = 0）
    ├ bldg:lod1Solid/gml:Solid/…/gml:Polygon             … 箱型。z の最大−最小 = LOD1 高さ
    ├ bldg:lod2Solid/gml:Solid/…/gml:surfaceMember @xlink:href  … boundedBy の面を参照するだけ
    ├ bldg:boundedBy/bldg:GroundSurface/bldg:lod2MultiSurface/…/gml:Polygon  … 地盤面
    ├ bldg:boundedBy/bldg:RoofSurface/bldg:lod2MultiSurface/…/gml:Polygon    … 屋根面（複数）
    │   └ gml:exterior/gml:LinearRing/gml:posList  (+ gml:interior …)   … "lat lon z lat lon z …"
    ├ bldg:boundedBy/bldg:WallSurface …           … 対象外
    ├ uro:buildingIDAttribute/uro:BuildingIDAttribute/uro:buildingID  … 例 13103-bldg-32194
    └ uro:bldgDataQualityAttribute/uro:DataQualityAttribute/uro:lodType, uro:lod1HeightType
```

- `lod2Solid` はジオメトリを持たず、`boundedBy` 配下の面を `xlink:href` で参照するだけ。ジオメトリは `boundedBy` 側から読む。
- LOD3 が整備された建物では、`boundedBy` に `bldg:lod3MultiSurface` を持つ面が別途並ぶ。本パイプラインは `bldg:lod2MultiSurface` のみを読む。
- 名前空間: `bldg = http://www.opengis.net/citygml/building/2.0`、`gml = http://www.opengis.net/gml`、`uro = https://www.geospatial.jp/iur/uro/3.2`。uro は版で URI が変わる（2023 年度データは 3.1）ので、`{https://www.geospatial.jp/iur/uro/*}` 相当のワイルドカードで扱う。
- `srsName` は `gml:Envelope` にしか付かず、ジオメトリ要素には付かない。座標順（緯度 経度 標高）は EPSG:6697 の定義に従い固定とし、`--lonlat` オプションで反転できるようにする。

---

## 3. 出力仕様

### 3.1 タイルセット

| 項目 | 値 |
| --- | --- |
| タイル形式 | MLT v1（主）、MVT（副） |
| コンテナ | PMTiles v3（MLT: tile_type 0x06、MVT: 0x01）。オプションで `{z}/{x}/{y}.mlt` ディレクトリ |
| ズーム | 10〜16（indigo-lab 版と同じ） |
| タイル圧縮 | PMTiles 内は gzip。ディレクトリ出力の `.mlt` は非圧縮 |
| レイヤー | `bldg`（1 レイヤー） |
| ジオメトリ | Polygon（屋根面 1 枚 = 1 フィーチャ、または屋根伏せ 1 面 = 1 フィーチャ） |
| 座標系 | WGS84 / Web メルカトル（tippecanoe 既定） |
| フィーチャ ID | tippecanoe `--generate-ids` による連番（MLT の feature-ID ソートに利用） |

### 3.2 属性

| 名前 | 型 | 内容 | 備考 |
| --- | --- | --- | --- |
| `z_cm` | int | 地盤面からの押し出し高さ [cm]（m × 100 を四捨五入） | `fill-extrusion-height` には `["*", ["get", "z_cm"], 0.01]` を渡す |
| `lod` | int | 形状の出所。`2` = RoofSurface、`1` = lod0RoofEdge + lod1Solid 高さ、`0` = lod0RoofEdge + measuredHeight | 表示のスタイル分岐、品質確認用 |
| `id` | string | `uro:buildingID`（無ければ `gml:id`） | 既定ではオフ。`--with-id` で付与（タイルサイズを優先） |

高さを indigo-lab 版のような float の `z`（m）ではなく整数の `z_cm` にした理由（PoC で判明、8.1 節）:

- tippecanoe は数値属性を値ごとに最も狭い MVT 型で書く（12.0 → sint、12.5 → float、5.4 → double）。`--attribute-type=z:float` を付けてもこの挙動は変わらない。
- `mlt convert` は型が混在した列を **文字列列** に変換する（値が `"Double(5.4)"`、`"Int(12)"` のような文字列になる）。MapLibre の `["get", "z"]` は文字列を返し、押し出し高さとして使えない。
- 整数だけの列なら MVT 側も常に sint で書かれ、MLT 側は整数列（U32）として正しく変換される。MLT の整数エンコーディング（FastPFOR、Delta）とも相性が良い。

全フィーチャで `z_cm` と `lod` は必ず整数、欠損は出さない（`null` を書かない）ことをスクリプト側で保証する。

### 3.3 高さの算出ルール

indigo-lab 版のルールを踏襲しつつ、面単位で持たせる。

1. LOD2（`bldg:RoofSurface/bldg:lod2MultiSurface` がある建物）
   - 対象ポリゴンは `RoofSurface` 配下の `lod2MultiSurface` に含まれる `gml:Polygon`。`lod3MultiSurface` は読まない。
   - 地盤高 `g` = 建物内の全 `GroundSurface`（`lod2MultiSurface`）の外周リング z の（最大 + 最小）/ 2。
   - 屋根面ポリゴンごとに高さ = そのポリゴンの外周リング z の（最大 + 最小）/ 2 − `g`。
   - 高さ < 0 になった場合は 0 にクランプ。`z_cm` = 高さ × 100 を四捨五入。
   - GroundSurface が無い建物は、建物内の全 `lod2MultiSurface` の z 最小値を `g` とする。
2. LOD2 以外
   - 形状は `bldg:lod0RoofEdge`（無ければ `bldg:lod0FootPrint`）の各ポリゴン。
   - 高さ = `lod1Solid` の z 最大 − z 最小（あれば、`lod = 1`）。無ければ `measuredHeight`（0 より大きい場合、`lod = 0`）。それも無ければ 0。
3. ポリゴンごとの 2D 面積が閾値（既定 0.1 m²）未満の屋根面は出力しない。

建物単位で 1 つの高さを持たせない理由: 千代田区の高層複合建物では低層部の屋根面（例: 約 22 m）と塔屋（例: 約 162 m）が同居し、建物全体の z の（最大 + 最小）/ 2 を採ると 283 棟で measuredHeight より 20 m 以上低くなった。面ごとに高さを持てば低層部と高層部がそれぞれの高さで立ち上がる。

### 3.4 TileJSON

```json
{
  "tilejson": "3.0.0",
  "name": "plateau-lod2-mlt",
  "tiles": ["https://<host>/tiles/{z}/{x}/{y}.mlt"],
  "format": "pbf",
  "encoding": "mlt",
  "minzoom": 10,
  "maxzoom": 16,
  "vector_layers": [{ "id": "bldg", "fields": { "z_cm": "Number", "lod": "Number" } }],
  "attribution": "..."
}
```

`encoding: "mlt"` は MapLibre GL JS 5.12 以降（Native Android 12.1 / iOS 6.2 系以降）が解釈する。MapLibre 公式デモ（`demotiles.maplibre.org/tiles-mlt/plain/tiles.json`）と同じ書き方。

### 3.5 MLT v1 仕様から設計に反映する点

[MapLibre Tile Specification](https://maplibre.org/maplibre-tile-spec/) の v1 仕様・エンコーディング・実装状況ページを確認した結果。

| 仕様上の事項 | 本設計での扱い |
| --- | --- |
| 列（属性）は 1 レイヤー内で単一の型。混在は「正規化が必要」 | 高さは整数 `z_cm`、`lod` も整数にして、tippecanoe が値ごとに型を変えられないようにする（3.2 節） |
| 列は nullable 可。欠損は型付き null になる | null を書かないことでデータ量と条件分岐を減らす。欠損時は 0 を入れる（3.3 節） |
| Feature ID は任意だが推奨。UInt32 に収まると FastPFOR が効く | tippecanoe `--generate-ids` の連番を使う。タイルごとに 32 bit に収まる |
| 整数列は Delta / RLE / FastPFOR、浮動小数は ALP や辞書で圧縮される | 高さを整数 cm で持つことで整数エンコーディングが使える |
| 圧縮のためにフィーチャの並び替えが行われ、元の順序は保たれない | 描画順に依存しないので問題なし。`mlt convert --sort auto` の既定で良い |
| ジオメトリは整数グリッド（extent 4096）で、ポリゴンの穴と MultiPolygon に対応 | 内周リングはそのまま保持できる。GeometryCollection は非対応だが使わない |
| 事前テッセレーション（三角形インデックス）は任意 | `--tessellate` あり・なしでサイズと描画速度を比較する（8.1 節） |
| v1 は 2D のみ。z 座標は v2 の計画項目 | 高さは属性 `z` として持つ（indigo-lab 版と同じ）。将来 v2 で z 座標に載せ替える余地がある |
| 外側の gzip は「エンコーディング選択に影響させない」方針 | PMTiles 内は gzip、ディレクトリ出力は非圧縮で、MLT 自体の設定は変えない |

実装状況ページの要点（2026-09 時点）: 生成ツールは Planetiler 0.10 以降、Martin 1.3 以降（1.9 以降は MVT と MLT を相互変換して配信）、Rust CLI `mlt`。tippecanoe と Tilemaker は「近日対応」。QGIS プラグインで `.mlt` を直接開けるので、生成タイルの目視確認に使える。deck.gl 側は loaders.gl 4.4 以降が対応。

### 3.6 対象建物の絞り込み

メッシュ単位の CityGML には隣接区の建物が含まれる（2.2 節）。区単位のタイルセットでは `--city 13101` で `uro:city` が一致する建物だけを変換する。理由は次の 2 つ。

- 隣接区の建物はメッシュ境界で不自然に途切れるため、区境で切れる方が見え方として自然。
- 将来、複数区のデータを合わせて 1 つのタイルセットにするとき、同じ建物が複数のデータセットから二重に入るのを防ぐ。

複数区をまとめて処理する場合は `--city` を複数指定するか、指定なしで全建物を対象にし、`uro:buildingID` で重複を除く。

---

## 4. 処理フロー

```text
udx/bldg/*.gml (CityGML 2.0, EPSG:6697)
   │  scripts/citygml2geojson.py --city 13101  … lxml iterparse、1 棟ずつ処理、ファイル単位で並列
   ▼
build/<name>.ndjson              … GeoJSON 1 行 1 フィーチャ（tippecanoe -P で並列読込可）
   │
   ├─ tippecanoe -o ──────────────▶ dist/<name>.mvt.pmtiles      … MVT / PMTiles（gzip）
   │                                   │  mlt convert --tile-compression gzip
   │                                   └─▶ dist/<name>.mlt.pmtiles … MLT / PMTiles（gzip、tile_type = mlt）
   │
   └─ [--dir のみ] tippecanoe -e --no-tile-compression ▶ build/<name>_mvt/{z}/{x}/{y}.pbf（中間物）
                                       │  mlt convert
                                       └─▶ dist/<name>/{z}/{x}/{y}.mlt + tiles.json … MLT ディレクトリ（非圧縮）
```

`mlt convert` は PMTiles / MBTiles 入力からはディレクトリを出力できない（PoC で確認）。そのためディレクトリ版は tippecanoe のディレクトリ出力を経由し、tippecanoe を 2 回実行する。ディレクトリ版は既定ではオフにした（8.4 節）。

### 4.1 CityGML → GeoJSON（`scripts/citygml2geojson.py`）

- 実行環境: Windows の Python 3.12 + lxml 5.3（確認済み）。WSL でも動く。
- 入力: `.gml` ファイルまたはディレクトリを複数。ファイル単位で `multiprocessing` により並列化（21 ファイル 2.03 GB の単体走査が 23 秒だったので、変換全体でも数分以内を見込む）。
- 出力: NDJSON（1 行 1 Feature）。`--gzip` で `.gz` 出力。
- 主な処理
  1. `iterparse(events=('end',), tag='{bldg}Building')` で 1 棟ずつ取り出し、処理後に `clear()` と先行兄弟の削除でメモリを解放する（1 ファイル最大 40 MB 程度なので DOM でも耐えるが、他都市の巨大ファイルに備える）。
  2. `posList`（および `gml:pos`）を 3 値ずつに分割し、`[lon, lat]` に並べ替える。`srsDimension` が 2 の場合にも対応。
  3. リングは閉じる（先頭と末尾が異なれば先頭を追加）。巻き方向は tippecanoe が正規化する。
  4. 3.3 節の高さルールで `z`、`lod` を決める。
  5. 2D 面積（緯度で補正した平面近似）が閾値未満なら破棄し、破棄数を集計する。
  6. 座標は小数 7 桁に丸める（約 1 cm。tippecanoe 側でズームごとに更に丸められる）。
- オプション: `--city`（`uro:city` で絞る。複数指定可）、`--min-area`（既定 0.1）、`--with-id`、`--include-outer-floor`（OuterFloorSurface を屋根面扱い）、`--lod2-only`、`--lonlat`、`--precision`、`--workers`。
- LOD0 の形状も無い建物は `lod1Solid` の底面（z が最も低い面）を最後の代替とする。
- 集計ログ: 棟数、LOD2 棟数、出力フィーチャ数（LOD 別）、破棄面数、measuredHeight 欠損数、GroundSurface 欠損数を標準エラーに出す。

#### 4.1.1 実装の参考にするもの

indigo-lab/plateau-lod2-mvt は変換スクリプトを公開しておらず（リポジトリの中身はタイル、README、デモ HTML のみ）、README に書かれた変換規則だけが手掛かりになる。そのため本スクリプトは次を根拠に新規実装する。

| 参考 | 使う部分 |
| --- | --- |
| indigo-lab README「ジオメトリ情報」「属性情報」 | RoofSurface 1 枚 = 1 ポリゴン、lod0RoofEdge / lod0FootPrint へのフォールバック、屋根・地盤の z の（最大 + 最小）/ 2 による高さ、という規則の原型 |
| 本設計書 2.2〜2.3 節の実測結果と、調査に使った走査スクリプト（`iterparse` で `bldg:Building` を 1 棟ずつ読み、`RoofSurface` / `GroundSurface` / `lod1Solid` の `posList` から z を集計） | 要素パス、名前空間、`srsName` の有無、`lod2MultiSurface` 限定、欠損値 -9999 など、実データで確認済みの前提。走査スクリプトの解析部をそのまま変換スクリプトの核にする |
| CityGML 2.0 Building モジュール / GML 3.1.1 | `gml:posList` と `gml:pos`、`gml:exterior` / `gml:interior`、`srsDimension`、`xlink:href` 参照の意味 |
| PLATEAU 標準製品仕様書（データセット同梱の `specification/*.pdf`、第 5 版） | EPSG:6697 の座標軸順（緯度・経度・標高）、`uro:buildingID`、`uro:lodType`、`uro:lod1HeightType` の定義 |
| PLATEAU GIS Converter（nusamai、Rust。手元に `nusamai-citygml` あり） | CityGML パーサの設計（名前空間の扱い、`geometry.rs` のポリゴン抽出、EPSG:6697 の扱い）を突き合わせ用に読む。依存はしない |
| lxml `iterparse` の定石（処理済み要素の `clear()` と先行兄弟の削除） | 数百 MB の GML でもメモリを一定に保つ |

GDAL の GML ドライバ（`.gfs` テンプレート）や PLATEAU GIS Converter の GeoJSON 出力を経由する案は、面の種別（Roof / Wall / Ground）と z 値を保ったまま屋根面だけを取り出す後処理が別途必要になるため採らない。

### 4.2 tippecanoe（`scripts/build_tiles.sh`）

WSL Ubuntu の tippecanoe v2.80.0（確認済み）で実行する。

```sh
tippecanoe -q -o dist/<name>.mvt.pmtiles --force \
  -Z10 -z16 -l bldg \
  --drop-densest-as-needed --drop-smallest-as-needed \
  --generate-ids --attribute-type=z_cm:int --attribute-type=lod:int \
  -P build/<name>.ndjson
```

- indigo-lab 版の `-ad -an -Z10 -z16 -l bldg -ai` を踏襲。`-e dist` を `-o *.pmtiles` に置き換える。`--dir` 指定時の 2 回目の実行では `-e build/<name>_mvt --no-tile-compression` にする。
- 低ズーム（10〜15）では 500 KB 上限に収めるために小さい建物が間引かれる。上限を変える場合は `--maximum-tile-bytes`。
- `-T` による型固定は保険。実際の型統一は整数属性にすることで担保する（3.2 節）。

### 4.3 MLT 変換

Rust 版 CLI `mlt` v0.1.34（`cargo install mlt`、WSL に導入済み。rustc 1.98 以上が必要でツールチェーンを更新した）を使う。

```sh
mlt convert --tile-compression gzip dist/<name>.mvt.pmtiles dist/<name>.mlt.pmtiles
mlt convert build/<name>_mvt dist/<name>          # --dir 時のみ。ディレクトリ → ディレクトリ（非圧縮 .mlt）
```

- 入力: `.pmtiles` / `.mbtiles` / タイルディレクトリ。出力: `.pmtiles` / `.mbtiles` / ディレクトリ。ただし PMTiles / MBTiles 入力 → ディレクトリ出力は不可、`--tile-compression` は PMTiles / MBTiles → PMTiles のときのみ有効。
- PoC（1 メッシュ、17 タイル）でのサイズ: MVT(gzip) 152.9 kB → MLT(非圧縮) 138.4 kB、MLT(gzip) 124.1 kB。z16 の 1 タイルでは MVT 16.9 kB（非圧縮）に対し MLT 8.5 kB。
- 既定でソート戦略（なし / Morton）を試して小さい方を採用、FastPFOR と FSST を有効化。`--tessellate` で事前テッセレーション（ポリゴン描画の高速化。サイズ増とのトレードオフなので PoC で比較）。
- `mlt decode -f geo-json` で任意タイルを GeoJSON に戻せるので検証に使う（8 節）。

### 4.4 tippecanoe の MLT 直接出力について

felt/tippecanoe には MLT 出力の要望（Issue #380、2026-01）があるが、v2.80 時点で未実装。実装されればステップ 4.3 は不要になる。Planetiler も MLT 出力に対応予定だが、本件は GeoJSON 入力なので tippecanoe + mlt convert の 2 段構成を採る。

---

## 5. ビューア設計（`index.html`）

- MapLibre GL JS 6.10.0（npm 最新、MLT は 5.12 で導入）と pmtiles.js（`TileType.Mlt = 6` に対応）を CDN から読み込む。
- ソース定義
  ```json
  "bldg": {
    "type": "vector",
    "encoding": "mlt",
    "url": "pmtiles://https://<host>/plateau-lod2.mlt.pmtiles",
    "minzoom": 10, "maxzoom": 16,
    "attribution": "..."
  }
  ```
  `--dir` で作ったディレクトリを使う場合は `"tiles": ["https://<host>/<name>/{z}/{x}/{y}.mlt"]`（絶対 URL）にする。
- レイヤーは indigo-lab 版の `fill-extrusion` をそのまま使う。`fill-extrusion-height: ["*", ["get", "z_cm"], 0.01]`、色は高さの 1 の位で塗り分け。`lod` による色分けをデバッグ用に用意する。
- 画面上のトグルで MLT / MVT の PMTiles を切り替え、Range リクエスト数と転送量を比較できるようにする。
- 背景は国土地理院 最適化ベクトルタイル（PMTiles 版 `optimal_bvmap-v1.pmtiles`）を淡色地図風スタイル（`style/gsi-pale.json`、gsi-cyberjapan/3dpc-3dtiles の `pale.json`）で描き、その上に建物レイヤーを追加する。当初はラスタの地理院タイル淡色地図だったが、2026-09-19 にベクトルへ変更した。出典表記に PLATEAU、国土地理院最適化ベクトルタイル、本リポジトリを含める。
- ローカル確認は Range リクエストに対応した静的サーバーが必要（PMTiles）。`npx serve` または `pmtiles serve` を使う。Python の `http.server` は Range 非対応なので使わない。

---

## 6. 配信

| 方法 | 対象 | 注意 |
| --- | --- | --- |
| GitHub Pages | `*.pmtiles` | **採用**。Range リクエストに対応（206 で返ることを確認）。1 ファイル 100 MB 制限。区単位なら収まる。超えたら R2 へ |
| GitHub Pages | `<name>/{z}/{x}/{y}.mlt` ディレクトリ（`--dir`） | indigo-lab 版と同じ運用。ファイル数が多くなる（複数区で数万ファイル）ため既定では作らない |
| Cloudflare R2 / S3 | `*.pmtiles` | Range リクエストと CORS の設定が必要。大規模化時の本命 |

---

## 7. リポジトリ構成

```text
plateau-lod2-mlt/
├ README.md              … 利用者向け（タイル URL、レイヤー定義、ライセンス）
├ docs/design.md         … 本書
├ scripts/
│  ├ citygml2geojson.py  … CityGML → NDJSON
│  ├ build_tiles.sh      … tippecanoe → PMTiles(MVT) → PMTiles(MLT)（--dir でディレクトリも）
│  └ verify.py           … 件数・属性・サイズの検証（8 節）
├ index.html             … デモビューア
├ style/gsi-pale.json    … 背景地図スタイル（地理院 最適化ベクトルタイル 淡色地図風）
├ build/                 … 中間生成物（git 管理外）
└ dist/                  … タイル成果物（git 管理外。配信先へアップロード）
```

---

## 8. 検証計画

### 8.1 PoC（千代田区 1 メッシュ）— 実施済み（2026-09-19）

`53394549_bldg_6697_op.gml` を `--city 13101` で処理（千代田区分 271 棟、うち LOD2 245 棟）し、全工程を通した。

| 確認項目 | 結果 |
| --- | --- |
| フィーチャ数 | 1,203（LOD2 屋根面 1,177 + LOD0 フォールバック 26。面積閾値で 8 面を除外） |
| 属性の型（float `z` の場合） | **問題あり**。tippecanoe が 29 面の整数値の高さを sint、80 面を float、348 面を double で書き、`mlt convert` はこの列を文字列列（`"Double(5.4)"`、`"Int(83)"`…）に変換した。`--attribute-type=z:float` では防げない |
| 対策 | 高さを整数 `z_cm` に変更。再変換後は MLT 側で `U32` 列になることを `mlt decode -f text` で確認 |
| サイズ（17 タイル） | MVT(gzip) 152.9 kB → MLT(非圧縮) 138.4 kB、MLT(gzip) 124.1 kB。z16 の 1 タイル: MVT 16.9 kB（非圧縮）→ MLT 8.5 kB |
| `mlt convert` の入出力制約 | PMTiles 入力からディレクトリ出力は不可。`--tile-compression` は PMTiles/MBTiles → PMTiles のみ。ディレクトリ版は tippecanoe `-e` 出力を経由（4 章） |
| `mlt decode -f geo-json` | 属性値・LOD 内訳が入力 NDJSON と一致 |

未実施: `--tessellate` あり・なしの比較、QGIS プラグインでの表示確認。

### 8.2 本検証（千代田区 2025 全域）— ビルド済み、表示確認は 8.3

| 項目 | 結果 |
| --- | --- |
| 入力 | 21 メッシュ、`--city 13101`。千代田区 12,558 棟（LOD2 9,788、LOD0 フォールバック 2,770） |
| 変換時間 | CityGML → NDJSON 4.6 秒（並列）。tippecanoe 2 回 + mlt convert 2 回で約 22 秒 |
| フィーチャ数 | 72,723（LOD2 69,953、LOD1 2,770。面積閾値で 1,414 面を除外）。期待値 72,712 との差は面積計算の丸め（閾値付近の面 11 枚）による |
| NDJSON | 17.8 MB |
| `chiyoda-lod2.mvt.pmtiles` | 5.9 MB（MVT gzip 11.3 MB 分） |
| `chiyoda-lod2.mlt.pmtiles` | 3.9 MB（MLT gzip 4.2 MB 分）。tile_type = mlt、tile compression = gzip |
| タイル数 | 107（z10: 1、z11: 2、z12: 4、z13: 4、z14: 8、z15: 23、z16: 65）。非圧縮 MLT の合計 3.2 MB、最大タイル 187 kB（z15）。`--dir` 出力で計測 |
| 属性列 | `z_cm`、`lod` ともに MLT で `U32` 列。z16 タイル 1 枚で 1,863 フィーチャ、`z_cm` はすべて整数 |
| TileJSON | `encoding: "mlt"`、`vector_layers.fields = { z_cm, lod }`、bounds / center は tippecanoe のメタデータから生成 |
| GitHub Pages 制限 | PMTiles 1 ファイル 100 MB 制限に対して十分小さい。区単位なら問題なし |
| 例外・二重出力 | LOD3 建物を含むファイルでもエラーなし。`lod2MultiSurface` 限定のため屋根面の二重出力なし |

MVT に対する MLT のサイズは PMTiles 全体で約 66%（5.9 MB → 3.9 MB）、gzip 前の生データでは約 37%（11.3 MB → 4.2 MB）。

### 8.3 表示確認 — 実施済み（2026-09-19、Chrome、ローカル配信 `npx serve`）

MapLibre GL JS 6.10.0 + pmtiles.js 4.5.0 のビューア（`index.html`）で、東京駅・丸の内（z15.5、pitch 60）を 3 ソースで表示した。

| ソース | 結果 |
| --- | --- |
| MLT / PMTiles | 描画あり。`querySourceFeatures` 78,447 件、画面内描画 68,137 件。属性は `{ z_cm: 268, lod: 2 }` のように整数で取得できる。Range リクエスト 22 回、転送量 約 1.0 MB |
| MVT / PMTiles | 描画あり（同じ見え方）。Range リクエスト 22 回、転送量 約 1.4 MB |
| MLT / `{z}/{x}/{y}.mlt` ディレクトリ（当時は既定出力） | 描画あり。`encoding: "mlt"` の `tiles` ソースとして読める。`querySourceFeatures` 53,418 件 |

- 3 ソースでデコードエラーなし。同じ視野で MLT の転送量は MVT の約 70%。
- 高層ビル（丸の内・大手町）は低層部と塔屋が別々の高さで立ち上がり、意図どおり。
- ビューア側の注意点: `tiles` の URL は絶対 URL にする（MapLibre の Worker 内で解決されるため、相対パスは `Failed to parse URL` になる）。MapLibre 6 系は ES モジュール配布のみなので `<script type="module">` で読み込む。
- 自動操作でのハマりどころ: タブが非表示（`document.visibilityState = hidden`）だと `requestAnimationFrame` が止まり、MapLibre はスタイルの読み込みすら行わない。確認時はタブを前面にする。

未実施: `--tessellate` の比較、QGIS プラグインでの確認。

GitHub Pages（<https://shiwaku.github.io/plateau-lod2-mlt-pipeline/>）では、index が 200、MLT PMTiles への Range リクエストが 206 で返ることを確認した。

### 8.4 ディレクトリ出力を既定から外した判断（2026-09-19）

3 ソースの表示確認後、`{z}/{x}/{y}.mlt` ディレクトリは既定の成果物から外し、`build_tiles.sh --dir` のオプションにした。理由は次のとおり。

- MLT 版 PMTiles だけで静的配信（GitHub Pages を含む）が成立する。
- ディレクトリ版のために tippecanoe を 2 回実行しており、ビルドが不必要に複雑になる。
- タイルをファイル単位で git に入れると、対象を複数区に広げたときに z16 のファイル数が数千〜数万に膨らむ。
- TileJSON のベース URL を配信先ごとに書き換える手間がなくなる。

残す用途は、`pmtiles://` を扱えないクライアントへの直接配信、indigo-lab 版 / frogcat 版と同じ URL 形式での差し替え、CDN でのタイル単位キャッシュ。必要になったら `--dir --base-url` で生成する。

---

## 9. リスクと未決事項

| # | 内容 | 対応方針 |
| --- | --- | --- |
| 1 | MLT の「列内の型固定」制約に tippecanoe 出力が抵触する | **発生を確認**（8.1 節）。高さを整数 `z_cm` にして解決。float 属性を追加する場合は同じ問題が起きるので、数値属性はすべて整数にする |
| 2 | `measuredHeight = -9999` が 2.7% あり、LOD0 フォールバックで 0 m の建物が出る | lod1Solid の z 差を優先し measuredHeight は予備にする（3.3 節） |
| 3 | 屋根面のうち急勾配な面（1.8%）が 2D で線状になり見た目のノイズになる | 面積閾値で除外。閾値は表示確認して調整 |
| 4 | LOD2 のオーバーハング（庇、低層部の上に張り出した屋根）は地面から立ち上がって描かれる | `fill-extrusion-base` 用の属性（面の最低 z − 地盤高）を持たせる案があるが、平屋根では base = height となり壁が消える。既定では採用せず、将来の検討事項とする |
| 5 | pmtiles.js と MapLibre の MLT 対応は新しく、細かな非互換が残る可能性 | バージョンを固定して記録する（MapLibre 6.10.0、pmtiles.js 4.5.0、mlt 0.1.34、tippecanoe 2.80.0）。MapLibre 6 系は ES モジュール配布のみなので `<script type="module">` で読み込む |
| 6 | Windows 上では tippecanoe と mlt が使えない | ビルドは WSL で行う。Python 変換は Windows / WSL どちらでも可 |
| 7 | uro 名前空間が版ごとに変わる（2023 年度 3.1、2025 年度 3.2） | ワイルドカードで扱う（2.3 節） |
| 8 | LOD3 建物で `lod3MultiSurface` の屋根面を読むと LOD2 と二重に出る | `lod2MultiSurface` のみ読む（確認済み、2.2 節） |
| 9 | ジオメトリ要素に `srsName` が無い | 座標順は EPSG:6697 固定とし、`--lonlat` で反転可能にする |
| 10 | 対象を広げると z16 のタイル数・ファイル数が多くなる | PMTiles を配信形態とし、ディレクトリ出力は `--dir` オプションに限定（8.4 節） |

---

## 10. ライセンスと出典表記

- 入力データは PLATEAU（国土交通省）のもので、PLATEAU Site Policy に基づき政府標準利用規約 2.0 / CC BY 4.0 / ODC BY / ODbL のいずれかで利用できる。生成タイルの配布時は出典（Project PLATEAU、対象自治体、年度）を表記する。
- indigo-lab 版の設計（ジオメトリ規則、高さ規則、tippecanoe オプション、デモのスタイル）を参考にしているため、README でリンクを示す。
- 生成タイルのライセンスは CC BY 4.0 とする予定（indigo-lab 版と同じ）。

## 11. 参考

- indigo-lab/plateau-lod2-mvt: https://github.com/indigo-lab/plateau-lod2-mvt
- MapLibre Tile Specification: https://maplibre.org/maplibre-tile-spec/ （v1 仕様 `specification/v1/`、エンコーディング `encodings/`、実装状況 `implementation-status/`）
- maplibre/maplibre-tile-spec リポジトリ: https://github.com/maplibre/maplibre-tile-spec
- MLT 発表記事（2026-01-23）: https://maplibre.org/news/2026-01-23-mlt-release/
- MapLibre Style Spec, vector source `encoding`: https://maplibre.org/maplibre-style-spec/sources/
- MLT 表示サンプル: https://maplibre.org/maplibre-gl-js/docs/examples/display-a-map-with-mlt/
- Rust CLI `mlt`: https://github.com/maplibre/maplibre-tile-spec/tree/main/rust/mlt
- PMTiles v3 spec（tile_type 0x06 = MapLibre Vector Tile）: https://github.com/protomaps/PMTiles/blob/main/spec/v3/spec.md
- tippecanoe MLT 出力の要望: https://github.com/felt/tippecanoe/issues/380
- 3D 都市モデル（Project PLATEAU）千代田区（2025 年度）: https://www.geospatial.jp/ckan/dataset/plateau-13101-chiyoda-ku-2025
