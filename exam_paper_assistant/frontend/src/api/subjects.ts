import { axiosClient } from './http';

export interface Subject {
  name: string;
  short_name: string;
  bank_id: number;
  edu_id: number;
}

type SubjectsResponse = { subjects: Subject[] };

export const getSubjects = async (): Promise<Subject[]> => {
  const { data } = await axiosClient.get<SubjectsResponse>('/api/subjects');
  return data.subjects;
};

