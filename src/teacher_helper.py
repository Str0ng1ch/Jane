"""
Teacher Helper - RAG-based assistant for teachers.

Uses andragogy sources (source_type="teacher") to help teachers
prepare lessons, find methodological materials, and get pedagogical advice.
"""

from typing import List, Dict, Any, Tuple, Optional
from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from .base_rag import BaseRAGChecker


DEFAULT_SYSTEM_PROMPT = """
Ты — опытная методистка и экспертка по андрагогике (обучению взрослых) и педагогике.
Твоя задача — помогать преподавателям готовиться к занятиям, находить методические материалы,
и давать практические рекомендации по проведению уроков.

Правила:
1. **Фокусируйся на запросе преподавателя** — это главное.
2. Давай конкретные, практические рекомендации, которые можно сразу применить.
3. Ссылайся на методические источники, когда это уместно.
4. Если преподаватель загрузил план урока — анализируй его и давай рекомендации по улучшению.
5. Предлагай конкретные техники, приёмы и активности.
6. Будь конструктивной и поддерживающей, но честной.

При ссылках на источники используй формат:
[Автор, Название работы, глава или страницы]
Не выдумывай источники — используй только предоставленный контекст.

Обращайся к преподавателю на "вы". 
Выделение жирным: **текст**
Не используй таблицы в ответе.
""".strip()


class RAGTeacherHelper(BaseRAGChecker):
    """
    RAG-based helper for teachers.
    
    Uses source_type="teacher" filter to search only andragogy/pedagogy materials.
    
    Usage:
        >>> helper = RAGTeacherHelper(retriever=retriever)
        >>> response, chunks = helper.generate_verdict(
        ...     assignment_text="План урока: ...",  # Optional lesson plan
        ...     essay_text="Как сделать урок интерактивным?",  # Query
        ...     top_k=5,
        ...     return_chunks=True
        ... )
    """

    def __init__(
        self,
        retriever,
        model_name: str = "gemma-3-27b-it/latest",
        system_prompt: str = None,
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ):
        super().__init__(
            retriever=retriever,
            model_name=model_name,
            system_prompt=system_prompt or DEFAULT_SYSTEM_PROMPT,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def retrieve_top_k(
        self,
        essay_text: str,
        top_k: int = 5
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Retrieve relevant chunks from teacher/andragogy sources only.
        
        Args:
            essay_text: Query text (teacher's question)
            top_k: Number of chunks to retrieve
            
        Returns:
            Tuple[List[Dict], List[str]]: chunks and their IDs
        """
        # Use source_type filter to get only teacher materials
        chunks = self.retriever.retrieve(
            query=essay_text,
            top_k=top_k,
            source_type="teacher",  # Only andragogy/pedagogy sources
        )
        
        result_chunks = []
        chunk_ids = []
        
        for chunk in chunks:
            parent_id = chunk.get("metadata", {}).get("chunk_id", "")
            if not parent_id:
                parent_id = str(hash(chunk.get("text", "")[:100]))
            
            result_chunks.append({
                "text": chunk.get("text", ""),
                "meta": chunk.get("metadata", {}),
            })
            chunk_ids.append(parent_id)
        
        return result_chunks, chunk_ids

    def build_prompt(
        self,
        assignment_text: str,
        essay_text: str,
        context: str
    ) -> ChatPromptTemplate:
        """
        Build prompt for teacher helper.
        
        Args:
            assignment_text: Lesson plan or additional context (optional)
            essay_text: Teacher's query
            context: Retrieved sources
            
        Returns:
            ChatPromptTemplate
        """
        # Determine if lesson plan was provided
        has_lesson_plan = bool(assignment_text and assignment_text.strip())
        
        if has_lesson_plan:
            human_template = (
                "ПЛАН УРОКА:\n{assignment}\n"
                "---\n\n"
                "ЗАПРОС ПРЕПОДАВАТЕЛЯ:\n{essay}\n"
                "---\n\n"
                "МЕТОДИЧЕСКИЕ ИСТОЧНИКИ:\n{context}\n"
                "---\n\n"
                "**Инструкция:**\n"
                "1. Проанализируй план урока.\n"
                "2. Ответь на запрос преподавателя.\n"
                "3. Дай конкретные рекомендации по улучшению урока.\n"
                "4. Предложи техники и приёмы из методических источников.\n"
                "5. Будь практичным — рекомендации должны быть применимы сразу.\n\n"
                "В конце добавь раздел:\n"
                "**Рекомендуемые источники:** [список использованных источников]"
            )
        else:
            human_template = (
                "ЗАПРОС ПРЕПОДАВАТЕЛЯ:\n{essay}\n"
                "---\n\n"
                "МЕТОДИЧЕСКИЕ ИСТОЧНИКИ:\n{context}\n"
                "---\n\n"
                "**Инструкция:**\n"
                "1. Внимательно прочитай запрос преподавателя.\n"
                "2. Дай конкретный, практический ответ.\n"
                "3. Предложи техники и приёмы из методических источников.\n"
                "4. Если уместно, приведи примеры применения.\n"
                "5. Будь практичным — рекомендации должны быть применимы сразу.\n\n"
                "В конце добавь раздел:\n"
                "**Рекомендуемые источники:** [список использованных источников]"
            )

        return ChatPromptTemplate.from_messages([
            SystemMessagePromptTemplate.from_template(self.system_prompt),
            HumanMessagePromptTemplate.from_template(human_template),
        ])
