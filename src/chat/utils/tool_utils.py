from typing import Tuple, Optional

def contains_tool_use(content: str) -> bool:
    """Check if content contains tool use XML tags"""
    tool_tags = [
        "use_mcp_tool",
        "access_mcp_resource"
    ]

    for tag in tool_tags:
        if f"<{tag}>" in content and f"</{tag}>" in content:
            return True
    return False

def split_content(content: str) -> Tuple[str, Optional[str]]:
    """Split content into plain text and tool definition parts.

    Args:
        content: The content to split

    Returns:
        Tuple[str, Optional[str]]: Tuple of (plain content, tool content)
    """
    tool_tags = [
        "use_mcp_tool",
        "access_mcp_resource"
    ]

    # Find the first tool tag
    first_tag_index = len(content)
    first_tag = None
    for tag in tool_tags:
        tag_start = content.find(f"<{tag}>")
        if tag_start != -1 and tag_start < first_tag_index:
            first_tag_index = tag_start
            first_tag = tag

    if first_tag_index < len(content) and first_tag:
        # Find the end of the tool block
        end_tag = f"</{first_tag}>"
        end_index = content.find(end_tag, first_tag_index)
        if end_index != -1:
            end_index += len(end_tag)

            # Extract tool content
            tool_content = content[first_tag_index:end_index].strip()

            # Combine content before and after tool block
            plain_content = (content[:first_tag_index] + content[end_index:]).strip()

            return plain_content, tool_content

    return content.strip(), None
