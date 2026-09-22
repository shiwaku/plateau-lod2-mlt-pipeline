# plateau-mlt-pipeline

[3D 都市モデル（Project PLATEAU）](https://www.mlit.go.jp/plateau/) の CityGML から、建築物（`bldg:Building`）の LOD2 屋根面を
[MapLibre Tile（MLT）](https://maplibre.org/maplibre-tile-spec/) と [PMTiles](https://github.com/protomaps/PMTiles) に変換するパイプラインです。
変換規則は [indigo-lab/plateau-lod2-mvt](https://github.com/indigo-lab/plateau-lod2-mvt) に準拠し、出力形式を MVT ディレクトリから MLT / PMTiles に置き換えています。

- デモ: <https://shiwaku.github.io/plateau-mlt-pipeline/>
- 実験ビューア（LOD3 / LOD4）: <https://shiwaku.github.io/plateau-mlt-pipeline/lod3-lod4.html>
- 設計書: [docs/design.md](docs/design.md)
- 検証データ: [3D 都市モデル（Project PLATEAU）千代田区（2025 年度）](https://www.geospatial.jp/ckan/dataset/plateau-13101-chiyoda-ku-2025)
- 東京 23 区の LOD 別整備量: [docs/tokyo23ku-lod-survey.md](docs/tokyo23ku-lod-survey.md)
- LOD3 / LOD4 を MLT にする実験: [docs/lod3-lod4-experiment.md](docs/lod3-lod4-experiment.md)

関連: [frogcat/plateau-lod2-mlt](https://github.com/frogcat/plateau-lod2-mlt) は indigo-lab 版の MVT（2020 年度・東京 23 区）を MLT に変換したものです。
本リポジトリは CityGML から直接変換するため、2023 年度以降のデータや他都市にも使え、PMTiles も出力します。

## 出力

| ファイル | 内容 |
| --- | --- |
| `dist/<name>.mlt.pmtiles` | MLT を格納した PMTiles（tile_type = mlt、gzip） |
| `dist/<name>.mvt.pmtiles` | MVT を格納した PMTiles（比較・互換用） |

PMTiles を読めないクライアント向けに、`build_tiles.sh --dir` で `dist/<name>/{z}/{x}/{y}.mlt` ディレクトリと TileJSON も出力できます（既定ではオフ）。

### タイル仕様

| 項目 | 値 |
| --- | --- |
| ズームレベル | 10〜16（10〜15 では 500 KB に収まるよう小さな建物が間引かれます） |
| レイヤー | `bldg` |
| ジオメトリ | Polygon。LOD2 の建物は `bldg:RoofSurface` の屋根面 1 枚 = 1 フィーチャ、それ以外は `bldg:lod0RoofEdge` の屋根伏せ 1 面 = 1 フィーチャ |
| 属性 `z_cm` | 地盤面からの高さ [cm]（整数）。`fill-extrusion-height` には `["*", ["get", "z_cm"], 0.01]` を渡します |
| 属性 `lod` | 2 = 屋根面（LOD2）、1 = 屋根伏せ + `lod1Solid` の高さ、0 = 屋根伏せ + `measuredHeight` |

高さの算出規則（indigo-lab 版準拠）:

- LOD2: 屋根面ポリゴンごとに「外周リングの z の（最大 + 最小）/ 2」−「`bldg:GroundSurface` の z の（最大 + 最小）/ 2」
- LOD2 以外: `bldg:lod1Solid` の z の最大 − 最小。無ければ `bldg:measuredHeight`（`-9999` は欠損扱い）。無ければ 0
- 2D 面積が 0.1 m² 未満の屋根面（ほぼ鉛直な面）は除外

高さを indigo-lab 版の float `z`（m）ではなく整数 `z_cm` にしているのは、tippecanoe が数値を値ごとに sint / float / double で書き分け、それを `mlt convert` が文字列列に変換してしまうためです（詳細は設計書 3.2 節）。

## 使い方

必要なもの: Python 3.12 + lxml（Windows でも可）、tippecanoe 2.17 以降、`mlt` CLI（`cargo install mlt`）、python3（ビルドは Linux / macOS / WSL）。

```sh
# 1. CityGML -> NDJSON（区コードで絞る。メッシュ単位のファイルには隣接区の建物も入っています）
python scripts/citygml2geojson.py path/to/udx/bldg -o build/chiyoda-lod2.ndjson --city 13101

# 2. NDJSON -> PMTiles(MVT) -> PMTiles(MLT)
bash scripts/build_tiles.sh build/chiyoda-lod2.ndjson chiyoda-lod2

# 3. ローカル確認（PMTiles には Range リクエスト対応のサーバーが必要）
npx serve .
# -> http://localhost:3000/  （index.html）
```

`citygml2geojson.py` の主なオプション: `--city CODE`（複数可）、`--min-area 0.1`、`--with-id`（`uro:buildingID` を付与）、`--include-outer-floor`、`--lod2-only`、`--workers N`。

## ビューア

`index.html` は MapLibre GL JS 6.10 + pmtiles.js で、MLT / PMTiles と MVT / PMTiles を切り替えて表示します。
背景地図は[国土地理院 最適化ベクトルタイル](https://github.com/gsi-cyberjapan/optimal_bvmap)（PMTiles 版）で、淡色地図風スタイル `style/gsi-pale.json`
（[gsi-cyberjapan/3dpc-3dtiles](https://github.com/gsi-cyberjapan/3dpc-3dtiles) の `public/styles/pale.json`）に建物レイヤーを重ねています。
`?base=https://<host>/path&name=chiyoda-lod2` でタイルの置き場所を指定できます。

MapLibre のソース定義は次のとおりです。

```json
{
  "type": "vector",
  "encoding": "mlt",
  "url": "pmtiles://https://<host>/chiyoda-lod2.mlt.pmtiles"
}
```

`encoding: "mlt"` は MapLibre GL JS 5.12 以降で使えます。

## 千代田区 2025 での結果

| 項目 | 値 |
| --- | --- |
| 建物 | 12,558 棟（LOD2 9,788 棟、屋根伏せフォールバック 2,770 棟） |
| フィーチャ | 72,723 |
| `chiyoda-lod2.mvt.pmtiles` | 5.9 MB |
| `chiyoda-lod2.mlt.pmtiles` | 3.9 MB（107 タイル） |
| ビューアでの転送量（東京駅周辺 z15.5、同一視野） | MLT/PMTiles 約 1.0 MB、MVT/PMTiles 約 1.4 MB |

MapLibre GL JS 6.10.0 + pmtiles.js 4.5.0 で両ソースの表示を確認しています。

## データの出典

| 用途 | データ | 提供元 | 備考 |
| --- | --- | --- | --- |
| 建物タイル（`dist/`） | [3D 都市モデル（Project PLATEAU）千代田区（2025 年度）](https://www.geospatial.jp/ckan/dataset/plateau-13101-chiyoda-ku-2025) CityGML（`13101_chiyoda-ku_pref_2025_citygml_1_op`、2026 年 3 月 16 日版） | 国土交通省 Project PLATEAU（G 空間情報センターで配布） | 標準製品仕様書 第 5 版準拠。`udx/bldg` の建築物のうち `uro:city = 13101` の 12,558 棟を変換。政府標準利用規約 2.0 / CC BY 4.0 / ODC BY / ODbL のいずれかで利用可（[PLATEAU Site Policy](https://www.mlit.go.jp/plateau/site-policy/)） |
| 背景地図 | [国土地理院 最適化ベクトルタイル](https://github.com/gsi-cyberjapan/optimal_bvmap)（PMTiles 版 `optimal_bvmap-v1.pmtiles`） | 国土地理院 | [国土地理院コンテンツ利用規約](https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html)に基づき利用。出典は「国土地理院最適化ベクトルタイル」 |
| 背景地図のスタイル | `style/gsi-pale.json`（[gsi-cyberjapan/3dpc-3dtiles](https://github.com/gsi-cyberjapan/3dpc-3dtiles) の `public/styles/pale.json`） | 国土地理院 | 淡色地図風スタイル。glyphs と sprite は `gsi-cyberjapan.github.io/optimal_bvmap` を参照 |
| 変換規則 | [indigo-lab/plateau-lod2-mvt](https://github.com/indigo-lab/plateau-lod2-mvt) | indigo-lab | ジオメトリ・高さの算出規則と tippecanoe オプションを踏襲（CC BY 4.0） |

元データに含まれない建物があります（例: 霞が関 2 丁目付近の官公庁）。詳細は [Issue #3](https://github.com/shiwaku/plateau-mlt-pipeline/issues/3) を参照してください。

## ライセンス

- 本リポジトリのコード（`scripts/`、`index.html`）は [MIT ライセンス](LICENSE)です。
- 生成したタイル（`dist/`）は CC BY 4.0 で提供します。利用の際は本リポジトリへのリンクと、上記の出典（国土交通省 Project PLATEAU）を示してください。
- 入力データは [Project PLATEAU](https://www.mlit.go.jp/plateau/) の 3D 都市モデル（国土交通省）を加工したものです。利用にあたっては [PLATEAU Site Policy](https://www.mlit.go.jp/plateau/site-policy/) を確認してください。
- 背景地図の利用は[国土地理院コンテンツ利用規約](https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html)に従ってください。
- 変換規則は [indigo-lab/plateau-lod2-mvt](https://github.com/indigo-lab/plateau-lod2-mvt)（CC BY 4.0）を参考にしています。
