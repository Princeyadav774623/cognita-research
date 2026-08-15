"""
Quick test script — run this first to verify everything works
before starting the full server.

Usage:
    cd backend
    python ../run.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from dotenv import load_dotenv
load_dotenv("backend/.env")

from graph.research_graph import run_research


async def main():
    print("\n" + "="*50)
    print("  Multi-Agent Research Assistant")
    print("="*50 + "\n")

    query = input("Enter your research question: ").strip()
    if not query:
        query = "What is LangGraph and how does it work?"

    print(f"\n🔍 Researching: {query}\n")
    print("Running agents... (this takes 15-30 seconds)\n")

    try:
        result = await run_research(query, session_id="test-001")

        print("\n" + "="*50)
        print("  FINAL REPORT")
        print("="*50)
        print(result["final_report"])
        print("\n" + "="*50)
        print(f"  Sources used: {len(result['source_documents'])}")
        print(f"  Confidence: {result['overall_confidence']:.0%}")
        print("="*50 + "\n")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nMake sure your .env file has GROQ_API_KEY and TAVILY_API_KEY set correctly.")


if __name__ == "__main__":
    asyncio.run(main())
