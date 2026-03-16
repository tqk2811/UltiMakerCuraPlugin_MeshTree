# UltiMakerCuraPlugin_MeshTree

Plugin Post-Processing Script cho UltiMaker Cura để điều chỉnh phần **ngọn (Tips)** của **Mesh Tree Support**.

## Tính năng

| Cài đặt | Mô tả |
|---|---|
| **Tip Flow Rate (%)** | Lượng nhựa phun ra cho phần ngọn. `100` = bình thường, `85` = ít nhựa hơn 15% |
| **Tip Layer Count** | Số lớp tính là "ngọn". `0` = chỉ lớp SUPPORT-INTERFACE, `2` = thêm 2 lớp support bên dưới |
| **Restore Flow After Tips** | Tự động khôi phục lượng nhựa về bình thường sau phần ngọn |
| **Add Comments to G-Code** | Thêm chú thích vào G-code để dễ kiểm tra |

## Cách hoạt động

Plugin phát hiện các lớp ngọn qua comment `;TYPE:SUPPORT-INTERFACE` trong G-code, sau đó chèn lệnh `M221 S<percent>` để thay đổi flow rate:

```gcode
;TYPE:SUPPORT-INTERFACE
M221 S85 ; [MeshTreeTipAdjuster] tip flow 85%
G1 F2400 X... Y... E...
;TYPE:WALL-OUTER
M221 S100 ; [MeshTreeTipAdjuster] restore flow
```

## Cài đặt

### Bước 1 — Sao chép file script

Sao chép file `MeshTreeTipAdjuster.py` vào **một trong hai** thư mục sau (chọn cách nào dễ hơn):

#### Cách 1 — Thư mục user (khuyến nghị, không cần quyền Admin)

**Windows:**
```
C:\Users\<tên_user>\AppData\Roaming\UltiMaker\Cura\<version>\scripts\
```
> Nếu thư mục `scripts` chưa có → **tạo mới** thư mục đó.

**macOS:**
```
~/Library/Application Support/cura/<version>/scripts/
```

**Linux:**
```
~/.local/share/cura/<version>/scripts/
```

#### Cách 2 — Thư mục cài đặt Cura (cần quyền Admin)

**Windows:**
```
C:\Program Files\UltiMaker Cura <version>\plugins\PostProcessingPlugin\scripts\
```
> `PostProcessingPlugin` là plugin có sẵn trong Cura, **không cần tạo**.

**macOS:**
```
/Applications/UltiMaker Cura.app/Contents/MacOS/plugins/PostProcessingPlugin/scripts/
```

### Bước 2 — Kích hoạt trong Cura

1. Mở UltiMaker Cura
2. Vào **Extensions** → **Post Processing** → **Modify G-Code**
3. Nhấn **Add a script**
4. Chọn **Mesh Tree Tip Adjuster**
5. Điều chỉnh các thông số theo nhu cầu
6. Slice như bình thường

## Yêu cầu

- UltiMaker Cura 5.x trở lên
- Bật **Tree Support** trong cài đặt slice
- Bật **Support Interface** (`support_interface_enable = true`) để plugin nhận diện được phần ngọn

## Cấu trúc file

```
MeshTreeTipAdjuster.py    ← Script chính (copy file này vào Cura)
README.md                 ← Tài liệu hướng dẫn
```
