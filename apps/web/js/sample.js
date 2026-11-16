/* 演示数据：只用于"看一眼效果"和自动截图，不会自动覆盖你的本地简历。 */

export const SAMPLE_DOCUMENT = {
  id: "r-demo0001",
  schemaVersion: "1.1",
  revision: 0,
  targetJob: "Python 后端开发",
  appearance: { template: "executive", theme: "navy", density: "balanced", zoom: 0.75 },
  recovery: [],
  modules: [
    {
      id: "mod-basic",
      type: "basic",
      order: 1,
      collapsed: true,
      data: {
        name: "张三",
        phone: "13800138000",
        email: "zhangsan@example.com",
        job: "Python 后端开发实习",
        github: "github.com/zhangsan",
      },
    },
    {
      id: "mod-edu",
      type: "education",
      order: 2,
      collapsed: true,
      data: {
        school: "江城大学",
        major: "计算机科学与技术",
        degree: "本科",
        time: "2022.09-2026.06",
        course: "数据结构、数据库系统、操作系统；GPA 3.7/4.0",
      },
    },
    {
      id: "mod-proj1",
      type: "project",
      order: 3,
      collapsed: true,
      data: {
        proj_name: "选课系统",
        role: "后端开发",
        time: "2025.03-2025.06",
        tech: "Flask / MySQL / Redis",
        desc: "负责选课接口与选课规则校验，支持 300 名学生同时选课；\n用 Redis 缓存课程余量，把超卖问题从每周 3 次降到 0。",
      },
    },
    {
      id: "mod-proj2",
      type: "project",
      order: 4,
      collapsed: true,
      data: {
        proj_name: "图书管理系统",
        role: "全栈",
        time: "2024.09-2024.12",
        tech: "Vue / FastAPI",
        desc: "负责前端页面与借阅接口，实现借还书与逾期提醒。",
      },
    },
    {
      id: "mod-skills",
      type: "skills",
      order: 5,
      collapsed: true,
      data: { skills: "Python、Flask、FastAPI、MySQL、Redis、Git、Linux" },
    },
    {
      id: "mod-honor",
      type: "honor",
      order: 6,
      collapsed: true,
      data: { honor_name: "校程序设计竞赛", time: "2024.05", level: "二等奖（校级）" },
    },
    {
      id: "mod-summary",
      type: "summary",
      order: 7,
      collapsed: true,
      data: { eval: "计算机专业大三，偏后端方向，习惯先把接口和边界条件写清楚再动手。" },
    },
  ],
};

export const SAMPLE_INSTRUCTION =
  "把选课系统的项目详情写得更专业一些，突出我负责的部分和结果，不要改数字。";
