import content from "./content.json";

export interface GuideItem {
  name: string;
  text: string;
}

export interface GuidePart {
  title: string;
  intro?: string;
  items: GuideItem[];
}

export interface GuideSection {
  id: string;
  group: string;
  title: string;
  href: string;
  summary: string;
  whenToUse: string;
  parts: GuidePart[];
  example: string | null;
  tips: string[];
}

export interface GuideOverview {
  title: string;
  paragraphs: string[];
  stepsTitle: string;
  steps: string[];
  glossary: Array<{ term: string; text: string }>;
}

export interface SettingsGuide {
  overview: GuideOverview;
  sections: GuideSection[];
}

/** Plain-English help for each setting. The same file produces `docs/user-guide/SETTINGS_GUIDE.md`
 * (run `npm run guide:docs`), so edit `content.json`, not the markdown. */
export const SETTINGS_GUIDE = content as SettingsGuide;

export function guideGroups(guide: SettingsGuide): Array<{ group: string; sections: GuideSection[] }> {
  const groups: Array<{ group: string; sections: GuideSection[] }> = [];
  for (const section of guide.sections) {
    const existing = groups.find((g) => g.group === section.group);
    if (existing) existing.sections.push(section);
    else groups.push({ group: section.group, sections: [section] });
  }
  return groups;
}
