# Architecture — Layout-Counter Azure Function

## Overview

The Layout-Counter is an internal Azure Function that:

1. Accepts a PDF office floorplan via HTTP POST.
2. Renders each PDF page to a PNG image using PyMuPDF.
3. Sends each image to Azure OpenAI GPT-4o (vision) to count furniture symbols.
4. Aggregates counts into a styled Excel workbook.
5. Uploads the workbook to SharePoint via Microsoft Graph.
6. Returns the SharePoint download URL to the caller.

---

## End-to-End Flow

```mermaid
flowchart TD
    PA[Power App / Teams]
    FN[Azure Function\nfunc-layout-counter\nPOST /api/process-floorplan]
    PDF[pdf_processor.py\nPyMuPDF → PNG tiles]
    DET[symbol_detector.py\nAsyncAzureOpenAI\nGPT-4o vision]
    AOAI[Azure OpenAI\naoai-layout-counter\ngpt-4o deployment]
    XLS[excel_builder.py\npandas + openpyxl]
    SP[sharepoint_uploader.py\nMicrosoft Graph PUT]
    SPSITE[(SharePoint\nIT-PowerAppStorage/\nLayout-Counter)]
    KV[Key Vault\nkv-layout-counter\nGraphClientSecret]
    LOG[App Insights\nappi-layout-counter]

    PA -->|PDF multipart/form-data| FN
    FN --> PDF
    PDF -->|list[PageImage]| DET
    DET -->|asyncio.gather x pages| AOAI
    AOAI -->|JSON counts| DET
    DET -->|list[PageResult]| XLS
    XLS -->|xlsx bytes| SP
    SP -->|GET token| KV
    SP -->|Graph PUT /content| SPSITE
    SPSITE -->|webUrl| SP
    SP -->|webUrl| FN
    FN -->|200 {url}| PA
    FN -->|structured logs| LOG
    DET -->|structured logs| LOG
```

---

## Component Descriptions

| Component | File | Description |
|---|---|---|
| HTTP Trigger | `function_app/function_app.py` | Python v2 model; validates PDF, orchestrates pipeline, returns JSON |
| PDF Renderer | `function_app/pdf_processor.py` | PyMuPDF at 200 DPI; tiles pages >4096 px |
| Symbol Detector | `function_app/symbol_detector.py` | Async GPT-4o calls, semaphore(5), JSON parse + retry |
| Excel Builder | `function_app/excel_builder.py` | pandas DataFrame + openpyxl styling |
| SharePoint Uploader | `function_app/sharepoint_uploader.py` | ClientSecretCredential → Graph API PUT |
| Config Loader | `function_app/config_loader.py` | Reads `config/furniture_categories.yaml` |
| Logging | `function_app/logging_config.py` | python-json-logger + opencensus App Insights handler |

---

## Authentication Summary

| Resource | Auth Method | Identity |
|---|---|---|
| Azure OpenAI | Managed Identity (DefaultAzureCredential) | Function App system-assigned MI |
| AzureWebJobsStorage | Identity-based connection | Function App system-assigned MI |
| Key Vault (secret read) | RBAC — Key Vault Secrets User | Function App system-assigned MI |
| Microsoft Graph / SharePoint | ClientSecretCredential | App registration `github-actions-sifcreation` |

---

## Infrastructure

All resources live in **resource group `rg-layout-counter`** in **East US**:

| Resource | Name | SKU |
|---|---|---|
| Log Analytics Workspace | `log-layout-counter` | PerGB2018 |
| Application Insights | `appi-layout-counter` | workspace-based |
| Storage Account | `stlayoutcounter` | Standard_LRS |
| Key Vault | `kv-layout-counter` | Standard, RBAC, soft-delete + purge protection |
| Azure OpenAI | `aoai-layout-counter` | S0, gpt-4o GlobalStandard |
| App Service Plan | `plan-layout-counter` | FC1 Flex Consumption, Linux |
| Function App | `func-layout-counter` | Python 3.11, system-assigned MI |
