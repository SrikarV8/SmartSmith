import React from "react";

/** Common first steps when starting a business — each one is a ready-made question. */
export interface Stage {
  numeral: string;
  name: string;
  tagline: string;
  prompt: string;
}

export const STAGES: Stage[] = [
  {
    numeral: "1",
    name: "Validate your idea",
    tagline: "Is there demand?",
    prompt:
      "I have a business idea. How do I validate that people will actually pay for it before I invest money?",
  },
  {
    numeral: "2",
    name: "Choose a legal structure",
    tagline: "LLC, S-corp and more",
    prompt:
      "Should I form an LLC, S-corp or sole proprietorship for a new small business in Texas, and how do I register it?",
  },
  {
    numeral: "3",
    name: "Costs and funding",
    tagline: "What you'll need",
    prompt:
      "What does it typically cost to start a small business, and what are my best options to fund it?",
  },
  {
    numeral: "4",
    name: "Write your plan",
    tagline: "A simple one-pager",
    prompt:
      "Walk me through writing a lean one-page business plan, including target market and value proposition.",
  },
  {
    numeral: "5",
    name: "Taxes and licenses",
    tagline: "Stay compliant",
    prompt:
      "What taxes, licenses and permits does a new small business need, and how do quarterly estimated taxes work?",
  },
  {
    numeral: "6",
    name: "Find your first customers",
    tagline: "On a small budget",
    prompt:
      "How do I find my first 10 paying customers on a small marketing budget?",
  },
];

export const Logo: React.FC<{ size?: number }> = ({ size = 28 }) => (
  <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true">
    <rect width="32" height="32" rx="8" fill="#b08968" />
    <path
      d="M7 12.5h15c0 1.8-1.9 2.8-4.4 2.8h-.9l.8 3.4H20V21H12v-2.3h2.5l.8-3.4h-.9c-2.6 0-4.7-1-6.4-2.8Z"
      fill="#181818"
    />
  </svg>
);

export const Sparks: React.FC = () => null;
