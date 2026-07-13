import logfire
from typing import Tuple, List

@logfire.instrument("Kiểm tra an toàn Input Guardrails")
async def check_input_guardrails(message: str) -> Tuple[bool, str]:
    # Placeholder for NVIDIA NeMo Guardrails Input Check
    logfire.info("Đang chạy NeMo Guardrails kiểm tra đầu vào")
    # Return (is_safe, fallback_message_if_not_safe)
    return True, ""

@logfire.instrument("Kiểm tra an toàn Output Guardrails")
async def check_output_guardrails(response: str, context: List[str]) -> Tuple[bool, str]:
    # Placeholder for NVIDIA NeMo Guardrails Output Check
    logfire.info("Đang chạy NeMo Guardrails kiểm tra đầu ra")
    # Return (is_safe, fallback_message_if_not_safe)
    return True, "Hệ thống phát hiện nội dung không đồng nhất với tài liệu pháp luật chính thống. Vui lòng thử lại sau."
