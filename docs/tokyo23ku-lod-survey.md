# 東京 23 区・最新年度データの LOD 別整備量（2026-09-20 調査）

本パイプラインの対象を広げる際の判断材料として、Project PLATEAU の東京 23 区データについて
**建築物モデルの LOD 別棟数**を整理したもの。あわせて LOD3 / LOD4 の所在も記録する。

数値は各データセットの `README.md`（CityGML zip 同梱）に記載された**整備量の宣言値**であり、
CityGML 要素の実数ではない。詳細は「5. 数値の性質」を参照。

## 1. 調査方法

G 空間情報センターの CKAN API と、配信サーバーの HTTP Range 対応を使う。CityGML zip 本体
（23 区合計 21.8 GB）はダウンロードしない。

1. `package_list` から `plateau-131xx-*-2025` を抽出し、区ごとの最新年度データセットを特定する
2. `package_show` で CityGML zip の URL を得る
3. zip の中央ディレクトリだけを Range リクエストで読み、`README.md` の1エントリのみ展開する
4. README の「建築物モデル」節を解析する

1 区あたり 1〜2 秒、転送量は数百 KB。再現用のコードは「6. 再現方法」に置いた。

## 2. 建築物モデルの LOD 別棟数

| 区 | 年度 | LOD1 | LOD2 系 | 内訳 | LOD3 |
| --- | --- | ---: | ---: | --- | ---: |
| 千代田 | 2025 | 12,576 | 9,788 | 2.0 5,341 / 2.2 4,447 | - |
| 中央 | 2025 | 16,797 | 16,785 | 2.0 5,752 / 2.2 11,033 | - |
| 港 | 2025 | 31,922 | 11,458 | 2.0 11,458 | - |
| 新宿 | 2025 | 57,782 | 6,500 | 2.0 2,726 / 2.2 3,774 | - |
| 文京 | 2025 | 39,367 | 319 | 2.0 319 | - |
| 台東 | 2024 | 40,861 | 15,539 | 2.0 15,510 / 2.2 29 | - |
| 墨田 | 2025 | 51,994 | 4,946 | 2.0・2.1 4,946 | 3 |
| 江東 | 2025 | 64,902 | 8,077 | 2.0 6,886 / 2.2 1,191 | - |
| 品川 | 2025 | 67,499 | 3,903 | 2.0 3,237 / 2.2 666 | - |
| 目黒 | 2025 | 55,638 | 949 | 2.0 949 | - |
| 大田 | 2025 | 158,860 | 2,855 | 2.0・2.1 2,855 | - |
| 世田谷 | 2025 | 206,432 | 1,930 | 2.0 1,930 | - |
| 渋谷 | 2025 | 41,626 | 4,575 | 2.0 1,917 / 2.2 2,658 | - |
| 中野 | 2025 | 73,225 | 1,735 | 2.0 1,735 | - |
| 杉並 | 2025 | 145,124 | 3,441 | 2.0 3,441 | - |
| 豊島 | 2025 | 56,894 | 6,470 | 2.0 2,785 / 2.2 3,685 | - |
| 北 | 2025 | 72,837 | 3,665 | 2.0 3,665 | - |
| 荒川 | 2025 | 44,128 | 795 | 2.0 795 | - |
| 板橋 | 2025 | 108,694 | 8,033 | 2.0 8,033 | - |
| 練馬 | 2025 | 182,670 | 2,118 | 2.0 2,118 | - |
| 足立 | 2025 | 169,212 | 4,186 | 2.0 4,186 | - |
| 葛飾 | 2025 | 118,889 | 3,297 | 2.0 3,297 | - |
| 江戸川 | 2025 | 145,366 | 3,990 | 2.0 3,990 | - |
| **計** | | **1,963,295** | **125,354** | | **3** |

LOD2 の整備率は 23 区全体で 6.4%。中央区 100%、千代田区 78%、台東区 38% と都心部は高く、
世田谷区 0.9%、練馬区 1.2% と周辺区は 1% 前後にとどまる。
本パイプラインは LOD2 が無い建物を `lod0RoofEdge` + 高さでフォールバックするため、
周辺区を対象にすると出力のほぼ全てが屋根伏せになる。

## 3. 「最新年度」データセットの落とし穴

年度が新しくても、そのデータセットが建築物モデルを含むとは限らない。

| 区 | 内容 |
| --- | --- |
| 台東区 | **2025 年度は `udx` に `brid` / `frn` / `tran` / `veg` のみで建築物モデルが無い**。表は 2024 年度を採用 |
| 港区 | 2025 年度は `bldg` と `htd` のみの部分更新。README から LOD2.2 と LOD3 の記載が消えている。2023 年度は LOD2.0 5,937 / LOD2.2 11,458 / **LOD3.0 102 棟（虎ノ門地区）** |

港区で LOD3 を扱うなら 2023 年度版を使う。

## 4. LOD3 / LOD4 の所在

| LOD | 所在 | 規模 |
| --- | --- | --- |
| 建築物 LOD3 | 港区 2023（虎ノ門地区） | 102 棟 |
| 建築物 LOD3 | 墨田区 2025（東京曳舟病院、イトーヨーカドー曳舟店、イーストコア曳舟） | 3 棟 |
| 建築物 LOD4 | [東京都 23 区 ポートシティ竹芝 建築物モデル（LOD4）（2022 年度）](https://www.geospatial.jp/ckan/dataset/plateau-tokyo23ku-2023-lod4)（BIM/IFC 由来の単独データセット） | 1 棟 |
| 地下街 LOD4.1 | 新宿区 2023（新宿駅周辺地下街）、千代田区 2025（東京駅周辺地下街） | 0.04 km² / 0.02 km² |

千代田区 2025 の `udx/bldg` にも LOD3 を持つ建物が 21 棟含まれるが、`uro:city` は全て `13103`（港区・虎ノ門）で、
メッシュが区界をまたぐことによる同梱。`--city 13101` で除外される。千代田区の建築物 LOD3 は実質ゼロ。

これらを本パイプラインで扱えない理由は [Issue #4](https://github.com/shiwaku/plateau-mlt-pipeline/issues/4) を参照。

## 5. 数値の性質

表の値は README の整備量宣言であり、CityGML 要素の実数ではない。
千代田区 2025 で実測したときは README 12,576 棟に対し `uro:city = 13101` の `bldg:Building` が 12,558 棟で、
18 棟の差があった。区界メッシュに含まれる隣接区の建物や、集計時点の違いが原因と考えられる。

実数が必要な場合は CityGML zip 21.8 GB（最大は中央区 2.5 GB）をダウンロードして走査する。

本ドキュメントの用途は「どの区にどの LOD がどれだけあるか」の概観なので、宣言値のまま使う
（差は千代田区で 0.14%、結論は変わらない）。23 区の実数調査は見送った（[Issue #9](https://github.com/shiwaku/plateau-mlt-pipeline/issues/9)）。

## 6. 再現方法

```python
import io, json, urllib.request, zipfile

class HTTPRangeFile(io.RawIOBase):
    def __init__(self, url):
        self.url, self.pos = url, 0
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=60) as r:
            self.size = int(r.headers["Content-Length"])
    def seekable(self): return True
    def readable(self): return True
    def seek(self, off, whence=0):
        self.pos = {0: off, 1: self.pos + off, 2: self.size + off}[whence]
        return self.pos
    def tell(self): return self.pos
    def read(self, n=-1):
        if n is None or n < 0: n = self.size - self.pos
        n = min(n, self.size - self.pos)
        if n <= 0: return b""
        req = urllib.request.Request(
            self.url, headers={"Range": "bytes=%d-%d" % (self.pos, self.pos + n - 1)})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        self.pos += len(data)
        return data
    def readinto(self, b):
        d = self.read(len(b)); b[: len(d)] = d; return len(d)

api = "https://www.geospatial.jp/ckan/api/3/action/package_show?id="
with urllib.request.urlopen(api + "plateau-13101-chiyoda-ku-2025", timeout=60) as r:
    pkg = json.load(r)["result"]
url = [x["url"] for x in pkg["resources"]
       if x["url"].endswith(".zip") and "citygml" in x["url"]][0]

z = zipfile.ZipFile(io.BufferedReader(HTTPRangeFile(url), buffer_size=1 << 16))
name = [x for x in z.namelist() if x.lower().endswith(".md")][0]
print(z.read(name).decode("utf-8-sig"))
```

データセット名は `package_list` を取得して `plateau-131` で始まるものを抽出すれば列挙できる。
README のファイル名は区によって `README.md` / `README_op.md` と揺れ、zip 直下にある場合と
`13103_minato-ku_city_2023_citygml_1_op/` のような 1 階層下にある場合がある。

## 7. 出典

- [3D 都市モデル（Project PLATEAU）](https://www.mlit.go.jp/plateau/)（国土交通省）。各区データセットは G 空間情報センターで配布
- 利用にあたっては [PLATEAU Site Policy](https://www.mlit.go.jp/plateau/site-policy/) を確認すること
