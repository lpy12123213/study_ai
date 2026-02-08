"""Lesson Plan Agent V2 - AI-powered lesson plan generation with streaming."""

from __future__ import annotations

import json
import asyncio
from typing import AsyncIterator, Optional, List, Dict, Any

from backend.core.settings import (
    LESSON_PLAN_API_KEY,
    LESSON_PLAN_BASE_URL,
    LESSON_PLAN_MAX_TOKENS,
    LESSON_PLAN_MODEL,
    LESSON_PLAN_TEMPERATURE,
)

SYSTEM_PROMPT = """You are an expert educational content creator specializing in lesson plan design.
Your task is to create comprehensive, engaging, and pedagogically sound lesson plans.

When creating a lesson plan, consider:
1. Clear learning objectives aligned with curriculum standards
2. Engaging introduction to capture student attention
3. Well-structured main content with varied activities
4. Assessment strategies to check understanding
5. Differentiation for diverse learners
6. Appropriate time allocation for each section

Output your lesson plan in a structured JSON format with the following fields:
- title: The lesson title
- objectives: Array of learning objectives with type (knowledge/skill/attitude)
- sections: Array of lesson sections with title, duration_minutes, content, activities, resources
- summary: Brief summary of the lesson

Be creative, practical, and student-centered in your approach."""


async def generate_lesson_plan_stream(
    subject: str,
    grade: str,
    topic: str,
    duration_minutes: int = 45,
    objectives: Optional[List[str]] = None,
    teaching_style: Optional[str] = None,
    student_level: Optional[str] = None,
    additional_requirements: Optional[str] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """
    Generate a lesson plan using AI with streaming events.
    
    Yields events with format:
    - {"event": "thinking", "data": {"content": "..."}}
    - {"event": "tool_call", "data": {"name": "...", "arguments": {...}}}
    - {"event": "content", "data": {"content": "...", "section": "..."}}
    - {"event": "done", "data": {"plan": {...}}}
    - {"event": "error", "data": {"message": "..."}}
    """
    try:
        # Yield initial thinking event
        yield {
            "event": "thinking",
            "data": {"content": f"Analyzing requirements for {subject} lesson on {topic}..."}
        }
        await asyncio.sleep(0.1)
        
        # Build the user prompt
        prompt_parts = [
            f"Create a {duration_minutes}-minute lesson plan for:",
            f"- Subject: {subject}",
            f"- Grade: {grade}",
            f"- Topic: {topic}",
        ]
        
        if objectives:
            prompt_parts.append(f"- Desired objectives: {', '.join(objectives)}")
        if teaching_style:
            prompt_parts.append(f"- Teaching style: {teaching_style}")
        if student_level:
            prompt_parts.append(f"- Student level: {student_level}")
        if additional_requirements:
            prompt_parts.append(f"- Additional requirements: {additional_requirements}")
        
        user_prompt = "\n".join(prompt_parts)
        
        yield {
            "event": "thinking",
            "data": {"content": "Designing lesson structure and activities..."}
        }
        await asyncio.sleep(0.1)
        
        # Check if API is configured
        if not LESSON_PLAN_API_KEY:
            # Generate a sample lesson plan without API
            yield {
                "event": "thinking",
                "data": {"content": "Generating lesson plan structure..."}
            }
            await asyncio.sleep(0.2)
            
            # Create a structured lesson plan
            plan = _create_sample_lesson_plan(
                subject, grade, topic, duration_minutes, objectives
            )
            
            # Stream sections
            for section in plan["sections"]:
                yield {
                    "event": "content",
                    "data": {
                        "content": section["content"],
                        "section": section["title"],
                    }
                }
                await asyncio.sleep(0.1)
            
            yield {
                "event": "done",
                "data": {"plan": plan}
            }
            return
        
        # Use OpenAI-compatible API for generation
        import httpx
        
        headers = {
            "Authorization": f"Bearer {LESSON_PLAN_API_KEY}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": LESSON_PLAN_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": LESSON_PLAN_TEMPERATURE,
            "max_tokens": LESSON_PLAN_MAX_TOKENS,
            "stream": True,
        }
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{LESSON_PLAN_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                if response.status_code != 200:
                    yield {
                        "event": "error",
                        "data": {"message": f"API error: {response.status_code}"}
                    }
                    return
                
                content_buffer = ""
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    
                    try:
                        chunk = json.loads(data)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            content_buffer += content
                            yield {
                                "event": "content",
                                "data": {"content": content, "section": "generation"}
                            }
                    except json.JSONDecodeError:
                        continue
                
                # Try to parse the final content as JSON
                try:
                    # Find JSON in the response
                    json_start = content_buffer.find("{")
                    json_end = content_buffer.rfind("}") + 1
                    if json_start >= 0 and json_end > json_start:
                        plan_json = content_buffer[json_start:json_end]
                        plan = json.loads(plan_json)
                        yield {
                            "event": "done",
                            "data": {"plan": plan}
                        }
                    else:
                        yield {
                            "event": "done",
                            "data": {"plan": {"content": content_buffer}}
                        }
                except json.JSONDecodeError:
                    yield {
                        "event": "done",
                        "data": {"plan": {"content": content_buffer}}
                    }
    
    except Exception as e:
        yield {
            "event": "error",
            "data": {"message": str(e)}
        }


def _create_sample_lesson_plan(
    subject: str,
    grade: str,
    topic: str,
    duration_minutes: int,
    objectives: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a sample lesson plan structure."""
    # Calculate time allocation
    intro_time = max(5, duration_minutes // 6)
    main_time = duration_minutes - intro_time - 10
    conclusion_time = 10
    
    return {
        "title": f"{topic} - {subject} Lesson",
        "subject": subject,
        "grade": grade,
        "topic": topic,
        "duration_minutes": duration_minutes,
        "objectives": [
            {"description": obj, "type": "knowledge"}
            for obj in (objectives or [f"Understand key concepts of {topic}"])
        ],
        "sections": [
            {
                "title": "Introduction",
                "duration_minutes": intro_time,
                "content": f"Begin with an engaging hook related to {topic}. "
                          f"Connect to prior knowledge and preview learning objectives.",
                "activities": ["Warm-up discussion", "Learning objectives review"],
                "resources": ["Whiteboard", "Presentation slides"],
            },
            {
                "title": "Main Content",
                "duration_minutes": main_time,
                "content": f"Present core concepts of {topic} through direct instruction "
                          f"and guided practice. Include interactive elements.",
                "activities": [
                    "Direct instruction",
                    "Guided practice",
                    "Pair/group discussion",
                ],
                "resources": ["Textbook", "Worksheets", "Digital resources"],
            },
            {
                "title": "Conclusion & Assessment",
                "duration_minutes": conclusion_time,
                "content": "Review key points, check for understanding, "
                          "and provide closure activities.",
                "activities": [
                    "Exit ticket",
                    "Summary discussion",
                    "Homework assignment",
                ],
                "resources": ["Exit ticket handout"],
            },
        ],
        "summary": f"A {duration_minutes}-minute lesson on {topic} for {grade} {subject} students.",
    }
