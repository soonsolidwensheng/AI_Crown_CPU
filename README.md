# Crown JSON Processor / AWS Lambda

`crownJsonProcessor` 提供统一的牙冠 JSON 处理能力：C++ 可处理文件或内存字符串，Python/Lambda 可处理 JSON 字符串、直接事件或 S3 presigned URL 任务。输入、输出、模型编码和逐牙错误语义完全一致。

基础网格、倒凹、缝合和碰撞算法的直接 C++ 接口，请参考[仓库根目录 README](../README.md)。

## 调用方式

### C++ 文件与字符串接口

Windows 动态库支持内存字符串和文件两种接口：

- `processJsonString()`：接收并返回完整 JSON 字符串；状态从返回 JSON 的 `crown.state` 读取。
- `processCrownJsonFile()`：读取输入文件、复用字符串处理逻辑并写出响应 JSON，保留 `bool` 和 `errorMessage` 语义。

完整签名、参数和错误语义见下文“1. 接口概述”。

### Python 绑定

从仓库根目录配置并构建 Windows Python 扩展：

```powershell
cmake -S . -B build-py -DBUILD_PY=ON -DCROWN_BUILD_TESTS=OFF
cmake --build build-py --config Release --target crownJsonProcessorPy
```

若 pybind11 没有作为 CMake package 安装，指定本地源码目录：

```powershell
cmake -S . -B build-py `
  -DBUILD_PY=ON `
  -DCROWN_BUILD_TESTS=OFF `
  -DCROWN_PYBIND11_SOURCE_DIR="F:\path\to\pybind11"
```

生成的 Python 扩展和运行库位于 `crownJsonProcessor_aws_lambda/crown/`，调用方式为：

```python
import crown

output_json = crown.process_crown_json(input_json_string)
```

### AWS Lambda

`index.py` 提供最小的 `handler(event, context)`。直接事件必须是本 README 的 JSON 接口接受的对象，即包含顶层 `crownInput`：

```json
{
  "crownInput": {
    "processType": "crown"
  }
}
```

也支持 S3 presigned URL。`source_url` 与 `target_url` 同时存在时，函数下载输入、处理后将完整结果上传到目标：

```json
{
  "source_url": "https://signed-s3-url/input.json",
  "target_url": "https://signed-s3-url/output.json",
  "job_id": "optional-job-id"
}
```

URL 模式只返回传输/处理状态；完整 Crown 结果写入 `target_url`：

```json
{
  "crown": {
    "state": {
      "status": "success",
      "errorCode": 200,
      "errorMsg": "success",
      "job_id": "optional-job-id"
    }
  }
}
```

上传使用 `Content-Type: application/json`。错误码：`211` 下载失败、`212` 处理失败、`213` 上传失败、`214` 处理响应无效、`215` 未捕获错误。只提供一个 URL 时仍按直接 JSON 事件处理。

## Docker runtime

先从仓库根目录构建 Linux Python 扩展，再收集额外系统运行库并构建镜像。CMake 会将 `crown*.so` 输出到 `crown/`，并自动将 Crown、VoxelCSG、mlCutMesh/MRMesh 及其私有运行库部署到 `crown/libs/`。

```bash
cmake -S . -B build-linux-py \
  -DBUILD_PY=ON \
  -DCROWN_BUILD_TESTS=OFF \
  -DCROWN_PYTHON_PACKAGE_DIR="$PWD/crownJsonProcessor_aws_lambda/crown"
cmake --build build-linux-py --config Release --target crownJsonProcessorPy

# 仅收集 ldd 发现、CMake 未随包部署的额外 Linux 运行库。
cd crownJsonProcessor_aws_lambda
./crown/copylibs.sh ./crown/crown*.so ./crown/libs
docker build -t crown-json-lambda .
```

镜像通过 `awslambdaric` 调用 `index.handler`，工作目录为 `/function/crown`。

## 本地包检查

```bash
python3 crown/test_crown.py
python3 crown/test_crown.py --input /path/to/crown-input.json
```

测试直接调用 `index.handler`，URL 路径使用本地 HTTP mock，不访问真实 S3。

## JSON 接口

以下章节定义 C++、Python 和 Lambda 直接 JSON 模式共用的输入、处理与输出协议。

### MQTest1 批量处理 JSON

现有 `MQTest1` 提供 JSON 批处理入口，不需要新增测试项目或可执行文件：

```powershell
MQTest1 --json <json-file-or-directory>
```

输入可以是单个 JSON 文件，也可以是目录：

```powershell
# 处理一个文件
MQTest1 --json "E:\\cases\\AABA-252S.json"

# 递归处理目录下所有 .json 文件
MQTest1 --json "E:\\cases"
```

### 输入和输出位置

- 传入单个文件时，结果保存到该文件所在目录的 `out/`：

  ```text
  E:\\cases\\AABA-252S.json
  E:\\cases\\out\\AABA-252S.json
  ```

- 传入目录时，结果保存到该目录下的 `out/`。
- 目录模式递归扫描所有扩展名为 `.json` 的普通文件，扩展名不区分大小写。
- 扫描时会跳过输入目录树中的 `out/` 目录，避免把之前生成的结果再次作为输入。
- 输出文件名与输入文件名相同，不保留输入子目录层级。
- 批次中不同子目录存在同名 JSON 时会发生输出路径冲突；冲突项不会覆盖结果，并计为失败。

### 批量处理行为

每个输入文件都会调用 `processCrownJsonFile`。某个文件失败后，MQTest1 会继续处理其他文件，并打印逐文件状态和最终汇总：

```text
[1/3] success: AABA-252S.json
[2/3] failed: invalid.json
       <error message>
[3/3] success: AABA-4YAV.json

JSON batch summary:
  total: 3
  succeeded: 2
  failed: 1
  output directory: E:\\cases\\out
```

返回值：

- `0`：全部 JSON 处理成功。
- `1`：至少一个 JSON 处理失败，但批处理已经完成。
- `2`：命令行参数错误、输入路径不存在、输入类型不支持或目录中没有 JSON 文件。

原有 `MQTest1` 的其他命令行模式和交互式输入模式保持不变。

### 1. 接口概述

Windows 动态库提供文件接口和内存字符串接口。字符串接口返回一个完整的 JSON 字符串，状态从返回 JSON 中读取：

```cpp
const std::string outputJson = crown::json::processJsonString(inputJson);
```

文件接口保留原有的 `bool` 和 `errorMessage` 参数，并复用同一套字符串处理逻辑：

```cpp
#include <crownJsonProcessor/CrownJsonProcessor.h>

std::string errorMessage;
const bool success = crown::json::processCrownJsonFile(
    "crown_input.json",
    "crown_output.json",
    errorMessage);
```

接口参数含义：

| 参数 | 含义 |
| --- | --- |
| `inputJsonPath` | 输入 JSON 文件路径。文件必须是 UTF-8 JSON。 |
| `outputJsonPath` | 输出 JSON 文件路径。父目录不存在时会自动创建。 |
| `errorMessage` | 接口级错误信息。调用前可以为空，调用后由接口清空并写入错误信息。 |
| 返回值 | 所有牙处理成功返回 `true`；存在处理失败的牙，或病例无法解析/写出时返回 `false`。 |

单颗牙失败不会停止其他牙的处理。只要病例结构可以解析，接口仍会尽可能写出包含逐牙错误信息的输出 JSON。

### 2. 输入模型与处理原理

#### 2.1 总体流程

输入 JSON 必须使用 `crownInput` 包裹完整病例：

```text
JSON 文件
  └─ crownInput
      ├─ 病例公共字段
      └─ 一个流程对象
          ├─ crown
          ├─ innerShell
          └─ shellStitch
```

处理器按以下顺序工作：

1. 读取 JSON 文件并解析根对象中的 `crownInput`。
2. 读取 `processType`，只解析对应的流程对象和模型字段。
3. 对每颗牙的 Draco Base64 模型进行解码，得到内存中的 `Mesh`。
4. `crown` 和 `innerShell` 优先使用 `stitcherOptions.underCutDir`，缺失时自动计算倒凹方向；`shellStitch` 必须提供该方向，不自动计算。
5. 根据流程生成内壳、最小厚度壳，或者使用已有内壳缝合外冠。
6. 保存每颗牙未解除碰撞的缝合冠快照。
7. 所有牙的生成阶段完成后，统一执行 `collisionToothIds` 指定的冠间碰撞和上下颌扫描模型碰撞。
8. `crown` 使用生成的最小厚度壳，`shellStitch` 使用输入的 `minShellModel`，最后执行最小厚度壳碰撞解除。
9. 将成功生成的结果网格重新压缩为 Draco Base64，写入输出 JSON。

`collisionToothIds` 中的每个目标牙使用其“未解除碰撞缝合冠快照”，并按数组顺序逐个执行碰撞解除。因此，一颗牙的碰撞处理不会改变另一颗牙后续作为碰撞参考模型的几何形状。

#### 2.2 三种流程的区别

| `processType` | 输入模型 | 主要处理 | 输出模型 | 碰撞处理 |
| --- | --- | --- | --- | --- |
| `crown` | `inner`、`outerCrownModel` | 根据备牙生成内壳和最小厚度壳，再缝合外冠 | `minShell`、`collisionRelievedCrown` | `collisionToothIds`、扫描模型，最后最小厚度壳 |
| `innerShell` | `inner` | 只根据备牙生成内壳和最小厚度壳 | `innerShell`、`minShell` | 不执行碰撞解除 |
| `shellStitch` | `innerShellModel`、`outerCrownModel`、必填 `underCutDir`、可选 `minShellModel` | 使用已有内壳缝合外冠 | `stitchedCrown` | `collisionToothIds`、扫描模型；最后可执行最小厚度壳碰撞 |

### 3. Draco Base64 模型

`inner`、`mesh_prep_extended`、所有 `*Model` 输入字段和输出模型字段都是标准 Base64 字符串，Base64 解码后是 Draco 三角网格数据。

位置属性使用固定 14 位量化。无法解码、模型没有有效位置属性、模型没有三角面，或者模型标签非法时，当前牙会处理失败。

#### 3.1 `StitchLabel` 的压缩

`Mesh::labels` 是逐面标签，而 Draco 属性是逐点属性。压缩带标签网格时执行以下转换：

1. 对每个面读取 `StitchLabel`。
2. 按 `(原顶点索引, 面标签)` 拆分顶点。
3. 将面标签转换为 `uint8` 顶点属性。
4. 使用拆点后的网格进行 Draco 压缩。

同一个原始顶点如果属于不同标签的面，会在压缩网格中生成多个点；同一个原始顶点属于相同标签的面时仍可共享一个点。

为与 Retainer 前端读取方式一致，带标签模型的第 0 个 Draco `GENERIC` 属性固定为这个单分量 `uint8` 标签。前端可按 `GENERIC 0` 读取；无标签模型不保证存在该属性。原始顶点索引和内部格式版本仍作为后续 `GENERIC` 属性保存，前端无需读取它们。

#### 3.2 `StitchLabel` 的解压

解压时读取每个三角形三个顶点的 `uint8` 标签：

- 三个顶点标签一致时，将该标签恢复为面的 `StitchLabel`。
- 三个顶点标签不一致时，认为 Draco 数据非法并抛出异常。
- 支持的标签值对应关系为：

| `uint8` 值 | `StitchLabel` |
| ---: | --- |
| `0` | `OUTER_CROWN` |
| `1` | `INNER_CROWN` |
| `2` | `STITCHER` |

压缩器还保存内部原始顶点索引属性。解压器发现该属性时会恢复原始顶点和面索引；没有该属性的外部 Draco 数据则保持 Draco 解压后的点顺序，不强制合并顶点。

### 4. 输入 JSON 公共字段

输入根对象示例：

```json
{
  "crownInput": {
    "version": "0.0.1",
    "caseId": "AABA-2CEB",
    "processType": "crown",
    "modelEncoding": "draco-base64",
    "upperJawModel": "...",
    "lowerJawModel": "...",
    "crown": {
      "teeth": []
    }
  }
}
```

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `crownInput` | object | 必填。完整病例输入包。 |
| `version` | string | 可选，默认 `"0.0.1"`。只要求是字符串，不校验版本内容。 |
| `caseId` | string | 可选，病例标识。缺失时输出空字符串。 |
| `processType` | string | 必填，只支持 `crown`、`innerShell`、`shellStitch`。 |
| `modelEncoding` | string | 可选，默认 `"draco-base64"`。当前只支持该值。 |
| `upperJawModel` | string | 可选的上颌扫描模型。仅在开启扫描模型碰撞时使用。 |
| `lowerJawModel` | string | 可选的下颌扫描模型。仅在开启扫描模型碰撞时使用。 |
| `crown` | object | `processType` 为 `crown` 时使用。 |
| `innerShell` | object | `processType` 为 `innerShell` 时使用。 |
| `shellStitch` | object | `processType` 为 `shellStitch` 时使用。 |

每个流程对象必须包含非空的 `teeth` 数组。处理器只读取当前 `processType` 对应的流程对象，避免三种流程的模型字段混用。

### 5. `crown` 输入

#### 5.1 示例

```json
{
  "crownInput": {
    "version": "0.0.1",
    "caseId": "AABA-2CEB",
    "processType": "crown",
    "modelEncoding": "draco-base64",
    "upperJawModel": "...",
    "lowerJawModel": "...",
    "crown": {
      "teeth": [
        {
          "toothId": "25",
          "collisionToothIds": ["26", "27", "35"],
          "inner": "...",
          "outerCrownModel": "...",
          "options": {
            "enableInnerCrownRepair": true,
            "stitcherOptions": {},
            "gapOptions": {},
            "collisionOptions": {
              "enableJawScanRelief": true,
              "enableMinShellRelief": true
            }
          }
        }
      ]
    }
  }
}
```

#### 5.2 牙齿字段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `toothId` | string | 必填，病例内唯一的牙齿 ID，例如 `"25"`。 |
| `collisionToothIds` | string[] | 统一的冠间碰撞目标 ID 数组，不区分邻牙和对颌牙；缺失、`null` 或空数组表示跳过冠间碰撞，非空数组按顺序逐个解除碰撞。 |
| `inner` | string | 必填。备牙/内冠 Draco Base64 模型；未重分割时直接用于生成内壳和计算倒凹方向。 |
| `control_pts_front` | number[3][] | 可选。轮廓点数组，每点格式为 `[x, y, z]`。仅与 `mesh_prep_extended` 同时存在时启用重分割评估；至少需要三个不同的有限点，首尾可重复。 |
| `mesh_prep_extended` | string | 可选。Draco Base64 扩展备牙网格。与 `control_pts_front` 同时存在时作为 mlCutMesh 切分源，`inner` 作为附加候选；选中的网格替代后续备牙输入。 |
| `outerCrownModel` | string | 已定位的外冠 Draco Base64 模型，用于外冠缝合。 |
| `options` | object | 当前牙的算法选项和碰撞开关。 |

`crown` 流程先生成内壳和最小厚度壳，再将外冠缝合到内壳上。最后输出的 `collisionRelievedCrown` 保留 `StitchLabel`，可以作为后续 `shellStitch` 的 `innerShellModel` 输入。

### 6. `innerShell` 输入

#### 6.1 示例

```json
{
  "crownInput": {
    "version": "0.0.1",
    "caseId": "AABA-2CEB",
    "processType": "innerShell",
    "modelEncoding": "draco-base64",
    "innerShell": {
      "teeth": [
        {
          "toothId": "25",
          "inner": "...",
          "options": {
            "enableInnerCrownRepair": true,
            "stitcherOptions": {},
            "gapOptions": {}
          }
        }
      ]
    }
  }
}
```

#### 6.2 牙齿字段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `toothId` | string | 必填，病例内唯一的牙齿 ID。 |
| `inner` | string | 必填，备牙/内冠 Draco Base64 模型。 |
| `control_pts_front` | number[3][] | 可选。与 `mesh_prep_extended` 同时存在时启用重分割评估。 |
| `mesh_prep_extended` | string | 可选。Draco Base64 扩展备牙网格；作为分割源，`inner` 作为附加候选。 |
| `options` | object | 内壳生成选项。 |

该流程不需要 `outerCrownModel`、`innerShellModel`、邻牙 ID、对颌牙 ID 或上下颌扫描模型，也不执行任何碰撞解除。

### 7. `shellStitch` 输入

#### 7.1 示例

```json
{
  "crownInput": {
    "version": "0.0.1",
    "caseId": "AABA-2CEB",
    "processType": "shellStitch",
    "modelEncoding": "draco-base64",
    "upperJawModel": "...",
    "lowerJawModel": "...",
    "shellStitch": {
      "teeth": [
        {
          "toothId": "25",
          "collisionToothIds": ["26", "27", "35"],
          "innerShellModel": "...",
          "outerCrownModel": "...",
          "minShellModel": "...",
          "options": {
            "stitcherOptions": {
              "underCutDir": [0.0, -1.0, 0.0]
            },
            "collisionOptions": {
              "enableJawScanRelief": true,
              "enableMinShellRelief": true
            }
          }
        }
      ]
    }
  }
}
```

#### 7.2 牙齿字段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `toothId` | string | 必填，病例内唯一的牙齿 ID。 |
| `collisionToothIds` | string[] | 统一的冠间碰撞目标 ID 数组，不区分邻牙和对颌牙；缺失、`null` 或空数组表示跳过冠间碰撞，非空数组按顺序逐个解除碰撞。 |
| `innerShellModel` | string | 已生成的内壳，或者带 `StitchLabel` 的完整冠 Draco Base64 模型。 |
| `outerCrownModel` | string | 已定位的外冠 Draco Base64 模型。 |
| `minShellModel` | string | 最小厚度壳 Draco Base64 模型。仅在 `enableMinShellRelief=true` 时必填和使用，通常来自 `crown` 或 `innerShell` 输出的 `minShell`。 |
| `options.stitcherOptions.underCutDir` | number[3] | 必填的倒凹/就位方向；必须是有限的非零向量。 |
| `options` | object | 外冠缝合选项和碰撞开关。 |

当 `innerShellModel` 含有至少一个 `OUTER_CROWN` 面标签时，处理器认为它是带标签的完整冠模型，并提取所有非 `OUTER_CROWN` 面作为内壳。没有 `OUTER_CROWN` 标签时，整个输入模型都作为内壳使用。

如果带标签模型提取后没有有效内壳，当前牙处理失败。

当 `enableMinShellRelief=true` 时，`minShellModel` 必须存在且是有效的 Draco 三角网格。它通常来自之前 `crown` 或 `innerShell` 流程输出的 `minShell`，只作为当前缝合冠的碰撞参考模型，不会作为 `shellStitch` 的输出。

`shellStitch` 完成所有牙的缝合后，碰撞顺序为：`collisionToothIds` 指定的冠间缝合冠、上下颌扫描模型，最后是 `minShellModel`。数组中的冠间模型按顺序逐个处理。因此输出的 `stitchedCrown` 已包含所有启用阶段的碰撞解除结果。

### 8. `options` 字段

`options`、`stitcherOptions` 和 `gapOptions` 都可以只传入部分字段。未传入的字段使用 C++ 算法结构中的默认值；但 `shellStitch` 的 `underCutDir` 是必填字段。字段类型错误或对象类型错误会导致当前牙处理失败。

#### 8.1 通用选项

| 字段 | 类型 | 默认值/说明 |
| --- | --- | --- |
| `enableInnerCrownRepair` | bool | 默认 `true`。是否在生成内壳前修复输入内冠的退化拓扑。对 `crown`、`innerShell` 有效。 |

#### 8.2 `stitcherOptions`

| 字段 | 类型 | 默认值 | 含义 |
| --- | --- | ---: | --- |
| `minWallThickness` | number | `0.5` | 最小壁厚。 |
| `wallHeight` | number | `1.5` | 边界壁厚从 `0.2 mm` 过渡到 `minWallThickness` 的测地距离，同时作为最小厚度壳缝合时的壁面影响高度。 |
| `marginLineOffset` | number | `0.08` | 边缘线偏移。 |
| `compensationAngle` | number | `60.0` | 补偿角度，算法要求在有效范围内。 |
| `extensionOffset` | number | `0.1` | 边缘外扩距离。 |
| `minShellOuterBoundaryTrimDistance` | number | `0` | 最小厚度壳外壳边界裁剪距离；正值按边界测地距离删除边缘带并平滑新边界，最大值为 `1`。 |
| `smoothInnerShellBoundary` | bool | `true` | 是否平滑内壳边界。 |
| `underCutDir` | number[3] | `crown`/`innerShell` 自动计算；`shellStitch` 必填 | 倒凹/就位方向。必须是有限的非零向量，输出时会归一化。 |

`outerDeformSmoothIterations`、`outerPostDeformSmoothIterations`、`outerPostDeformNoMoveRingCount`、`outerSubdivisionTargetEdgeLength` 和 `outerDeformSurfaceDistance` 仅适用于 `shellStitch` 模式，默认值分别为 `20`、`20`、`4`、`0.1` 和 `0.0`。`enablePostStitchLaplacianSmoothing` 同时适用于 `crown` 和 `shellStitch`，默认值为 `false`；开启后，过渡/延伸点会与现有外冠 6 圈一起进行缝合后拉普拉斯平滑。

`underCutDir` 的自动计算来源：

- `crown`：使用 `inner`，并在同时提供 `control_pts_front` 与 `mesh_prep_extended` 时使用轮廓选择结果。
- `innerShell`：使用 `inner`，并在同时提供 `control_pts_front` 与 `mesh_prep_extended` 时使用轮廓选择结果。
- `shellStitch`：不自动计算，必须由调用方提供方向；带标签模型仍会先提取内壳用于缝合。

#### 8.3 `gapOptions`

| 字段 | 类型 | 默认值 | 含义 |
| --- | --- | ---: | --- |
| `defaultCementGap` | number | `0.045` | 靠近边缘区域的默认水泥间隙。 |
| `extraCementGap` | number | `0.085` | 远离边缘区域的额外水泥间隙。 |
| `distanceToMarginLine` | number | `1.0` | 从边缘线开始计算过渡的距离。 |
| `smoothTransitionDistance` | number | `0.2` | 从默认间隙过渡到额外间隙的距离。 |
| `useColor` | bool | `false` | 是否写入用于观察间隙的颜色信息。 |

#### 8.4 `collisionOptions`

JSON 不暴露碰撞解除的距离、平滑次数、强度、过渡范围等数值参数。冠间碰撞是否执行由 `collisionToothIds` 是否非空决定；扫描模型和最小厚度壳仍使用以下开关：

| 字段 | 类型 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `enableJawScanRelief` | bool | `false` | 是否使用顶层上下颌扫描模型执行碰撞解除。 |
| `enableMinShellRelief` | bool | `false` | `crown` 使用生成的最小厚度壳，`shellStitch` 使用输入的 `minShellModel`，最后执行碰撞解除。 |

程序内部使用固定的 `crown::relief::CollisionReliefOptions`，并始终关闭调试网格输出。

`enableMinShellRelief` 在 `crown` 和 `shellStitch` 流程中有意义；`innerShell` 不执行碰撞。`shellStitch` 开启该开关时必须提供有效的 `minShellModel`。

### 9. ID 引用和模型检查规则

- `toothId` 必填，且在当前病例的 `teeth` 数组内唯一。
- `collisionToothIds` 是统一的冠间碰撞目标数组；字段缺失、`null` 或空数组表示跳过冠间碰撞。病例中不存在的目标 ID 会直接忽略，全部目标都不存在时该阶段为 `notRun`；病例中存在但未生成可用缝合冠的目标会使当前阶段失败。
- `collisionToothIds` 中的重复 ID 按首次出现顺序自动去重；旧的 `neighborToothId`、`opposingToothIds`、`enableNeighborRelief` 和 `enableOpposingCrownRelief` 均不再支持，出现时当前牙输入失败。
- `upperJawModel` 和 `lowerJawModel` 只有在至少一颗牙开启 `enableJawScanRelief=true` 时才解码。
- 扫描模型缺失时跳过扫描模型碰撞；扫描模型存在但 Draco 解码失败时，启用该碰撞的牙会失败。
- 邻牙或对颌牙引用的牙齿生成失败时，引用该牙的碰撞阶段失败，但其他牙仍继续处理。
- `shellStitch` 中开启 `enableMinShellRelief` 时必须提供有效的 `minShellModel`；缺失或解码失败会使当前牙失败，但其他牙仍继续处理。
- `crown` 和 `innerShell` 缺少或为 `null` 的 `underCutDir` 时使用内部自动计算；存在时必须是三个有限数值组成的非零向量。
- `shellStitch` 必须提供 `underCutDir`，且必须是三个有限数值组成的非零向量；缺失或非法时当前牙失败。
- 模型字段必须是非空 Draco Base64 字符串。

### 10. 输出 JSON

输出 JSON 使用 `crown` 包装，执行结果放在 `crown.result`，状态放在 `crown.state`：

```json
{
  "crown": {
    "result": {
      "version": "0.0.1",
      "caseId": "AABA-2CEB",
      "processType": "crown",
      "modelEncoding": "draco-base64",
      "teeth": [
        {
          "toothId": "25",
          "underCutDir": [0.0, -1.0, 0.0],
          "success": true,
          "collision": {
            "neighbor": "applied",
            "opposingCrown": "applied",
            "jawScan": "skipped",
            "minShell": "applied"
          },
          "minShell": "...",
          "collisionRelievedCrown": "..."
        }
      ],
      "summary": {
        "toothCount": 1,
        "successCount": 1,
        "failureCount": 0
      }
    },
    "state": {
      "errorCode": 200,
      "errorMsg": "success"
    }
  }
}
```

文档级异常也返回合法 JSON，`crown.result` 为 `null`，`crown.state.errorCode` 为非 `200`。

#### 10.1 `crown.result` 字段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `version` | string | 原样返回输入版本，缺失时为 `"0.0.1"`。 |
| `caseId` | string | 原样返回输入病例 ID。 |
| `processType` | string | 当前处理流程。 |
| `modelEncoding` | string | 当前固定为 `"draco-base64"`。 |
| `teeth` | object[] | 每颗牙的处理结果，顺序与输入一致。 |
| `summary` | object | 病例处理统计。 |

#### 10.2 牙齿结果字段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `toothId` | string | 当前牙齿 ID。 |
| `underCutDir` | number[3] | 实际使用的归一化倒凹方向。方向计算或模型生成失败时可能不存在。 |
| `success` | bool | 当前牙是否完成对应流程及其启用的碰撞阶段。 |
| `error` | string | `success=false` 时的错误信息。 |
| `collision` | object | 四类碰撞阶段的执行状态。 |

成功牙齿会包含当前流程对应的模型字段；失败牙齿只写入状态和错误，不写入不完整模型。

#### 10.3 流程输出模型

| `processType` | 输出字段 | 含义 |
| --- | --- | --- |
| `crown` | `minShell` | 最小厚度壳，编码为 Draco Base64。 |
| `crown` | `collisionRelievedCrown` | 完成缝合及启用碰撞解除后的完整冠，保留 `StitchLabel`。 |
| `innerShell` | `innerShell` | 生成的内壳。 |
| `innerShell` | `minShell` | 生成的最小厚度壳。 |
| `shellStitch` | `stitchedCrown` | 使用已有内壳缝合后的完整冠。 |

#### 10.4 碰撞状态

`collision` 包含以下字段：

| 字段 | 含义 |
| --- | --- |
| `neighbor` | 统一冠间碰撞解除状态；名称为兼容保留，不再表示邻牙。 |
| `opposingCrown` | 兼容保留字段，统一冠间碰撞流程使用 `neighbor`，此字段为 `notApplicable`。 |
| `jawScan` | 上下颌扫描模型碰撞解除状态。 |
| `minShell` | 最小厚度壳碰撞解除状态。 |

常见状态值：

| 状态 | 含义 |
| --- | --- |
| `applied` | 已执行该碰撞解除阶段。 |
| `disabled` | 输入开关未开启。 |
| `skipped` | 开关已开启，但缺少可用的上下颌扫描模型，因此跳过。 |
| `failed` | 该阶段执行失败，错误会追加到牙齿的 `error`。 |
| `notApplicable` | 当前流程不适用，例如 `innerShell` 的全部碰撞。 |
| `notRun` | 牙齿生成未成功，因此没有进入该碰撞阶段。 |

#### 10.5 `summary`

| 字段 | 含义 |
| --- | --- |
| `toothCount` | 输入牙齿数量。 |
| `successCount` | 成功处理的牙齿数量。 |
| `failureCount` | 失败牙齿数量。 |

### 11. 返回值和错误处理

#### 11.1 所有牙成功

当所有牙完成对应流程及启用的碰撞阶段时：

- 输出 JSON 正常写出。
- 每颗牙的 `success` 为 `true`。
- `failureCount` 为 `0`。
- `crown.state.errorCode` 为 `200`，`crown.state.errorMsg` 为 `"success"`。
- C++ 接口返回 `true`。
- `errorMessage` 为空。

#### 11.2 部分牙失败

当某些牙解码、倒凹方向计算、内壳生成、外冠缝合或碰撞解除失败时：

- 其他牙继续处理。
- 输出 JSON 仍然写出。
- 失败牙的 `success` 为 `false`，并包含 `error`。
- `summary.failureCount` 反映失败数量。
- `crown.state.errorCode` 为非 `200`，`crown.state.errorMsg` 按 `toothId=...: ...` 格式叠加所有失败牙信息。
- C++ 接口返回 `false`。
- `errorMessage` 与 `crown.state.errorMsg` 保持一致。

#### 11.3 病例级失败

以下错误会在病例处理阶段直接返回 `false`，并返回 `crown.result=null` 的状态 JSON：

- 输入文件无法读取。
- JSON 格式错误。
- 缺少 `crownInput`、`processType` 或对应流程对象。
- `processType` 或 `modelEncoding` 不支持。
- 输出文件无法创建或写入。

具体异常信息同时写入 `errorMessage` 和 `crown.state.errorMsg`。

### 12. 样例文件

仓库中的真实病例输入样例位于：

- `examples/crown-input/us/AABA-252S.json`
- `examples/crown-input/us/AABA-2CEB.json`
- `examples/crown-input/us/AABA-4YAV.json`

这些样例使用 `crownInput` 包装，并按照 `crown.teeth` 的流程结构组织输入。模型字段内容较长，接口文档中的 `"..."` 仅表示占位符，不是实际可解码的模型数据。
