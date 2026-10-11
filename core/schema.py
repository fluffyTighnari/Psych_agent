from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Document:
    doc_id: str
    content: str
    title: str
    source: str
    doc_type: str
    relative_path: str
    knowledge_path: str
    summary: str
    topic: list[str]
    keywords: list[str]
    emotion: dict
    problem: Optional[str] = None
    analysis: Optional[str] = None
    solution: Optional[str] = None
    date: Optional[str] = None
    word_count: int = 0
    embedding: Optional[object] = field(default=None, repr=False)

    def __repr__(self):
        return (
            f"Document("
            f"title='{self.title}', "
            f"type='{self.doc_type}', "
            f"words={self.word_count})"
        )

    def __str__(self):
        lines = [
            f"===== Document({self.doc_type}) =====",
            f"ID: {self.doc_id}",
            f"Title: {self.title}",
            f"Date: {self.date if self.date else '无'}",
            f"Path: {self.relative_path}",
            f"Knowledge_path: {self.knowledge_path}",
            f"WordCount: {self.word_count}",
            f"Summary: {self.summary[:100]}..." if len(self.summary) > 100 else f"Summary: {self.summary}",
            f"Topics: {self.topic}",
            f"Keywords: {self.keywords}",
            f"Emotion: {self.emotion}",
        ]
        if self.problem:
            lines.append(f"Problem: {self.problem}")
        if self.analysis:
            lines.append(f"Analysis: {self.analysis}")
        if self.solution:
            lines.append(f"Solution: {self.solution}")
        lines.append("=" * 40)
        return "\n".join(lines)



def create_document(
    doc_id,
    content,
    title,
    source,
    doc_type,
    relative_path,
    knowledge_path,
    summary,
    topic,
    keywords,
    emotion,
    problem=None,
    analysis=None,
    solution=None,
    date=None,
    word_count=0,
):

    return Document(
        doc_id = doc_id,
        content = content,
        title = title,
        source = source,
        doc_type = doc_type,
        relative_path = relative_path,
        knowledge_path = knowledge_path,
        summary = summary,
        topic = topic,
        keywords = keywords,
        emotion = emotion,
        problem = problem,
        analysis = analysis,
        solution = solution,
        date = date,
        word_count = word_count,
    )


@dataclass
class Memory:
    id: str
    start_time: str
    end_time: str
    title: str
    summary: str
    topics: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    emotion: dict = field(default_factory=dict)
    dialogues: list[dict] = field(default_factory=list)
    insights: list[str] = field(default_factory=list)
    referenced_documents: list[str] = field(default_factory=list)
    related_memory: list[str] = field(default_factory=list)
    guided_reasons: list[dict] = field(default_factory=list)

    def __repr__(self):
        return f"Memory(id='{self.id}', title='{self.title}', topics={self.topics})"


def create_memory(
    mem_id,
    start_time,
    end_time,
    title,
    summary,
    topics=None,
    keywords=None,
    emotion=None,
    dialogues=None,
    insights=None,
    referenced_documents=None,
    related_memory=None,
    guided_reasons=None,
):
    return Memory(
        id=mem_id,
        start_time=start_time,
        end_time=end_time,
        title=title,
        summary=summary,
        topics=topics or [],
        keywords=keywords or [],
        emotion=emotion or {},
        dialogues=dialogues or [],
        insights=insights or [],
        referenced_documents=referenced_documents or [],
        related_memory=related_memory or [],
        guided_reasons=guided_reasons or [],
    )